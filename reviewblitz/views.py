import urllib

from django.conf import settings
from django.db.models import Sum
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.views.generic import ListView, FormView, TemplateView, DetailView
from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist

from forum.models import MemberPage, get_soup
from forum.views import LoginRequiredMixin, VerificationRequiredMixin, ForumObjectLookupView
from forum.utils import forum_url_from_path
from reviewblitz.models import BlitzReview, ReviewBlitz, ReviewChapterLink, BlitzUser
from reviewblitz.forms import BlitzReviewSubmissionForm, ChapterLinkFormSet, HasReviewedForm


class BlitzReviewSubmissionFormView(LoginRequiredMixin, VerificationRequiredMixin, FormView):
    form_class = BlitzReviewSubmissionForm
    template_name = "blitz_review_submit.html"

    def form_valid(self, form):
        review = form.cleaned_data["review"]
        review.chapters = form.cleaned_data["chapters"]
        review.save()

        blitz = ReviewBlitz.get_current()

        # Has this review already been submitted for this Blitz?
        try:
            blitzreview = BlitzReview.objects.get(blitz=blitz, review=review)
        except BlitzReview.DoesNotExist:
            blitzreview = BlitzReview(blitz=blitz, review=review)

        week_index = blitzreview.week_index()
        print(f"This review was posted in week {week_index} of the Blitz.")

        weekly_theme = blitzreview.get_theme()
        prev_reviews = BlitzReview.objects.filter(blitz=blitz, review__author=review.author, review__fic=review.fic)
        if blitzreview.id:
            prev_reviews = prev_reviews.filter(id__lt=blitzreview.id)

        # Find how many effective chapters (i.e. number of chapters or increments of the Blitz's
        # words per chapter, whichever is smaller) we've already reviewed of this fic this Blitz.
        prev_chapters_reviewed = 0
        for r in prev_reviews:
            effective_chapters_reviewed = r.effective_chapters_reviewed()
            prev_chapters_reviewed += r.effective_chapters_reviewed()
            print(f"Previous review - effective chapters reviewed: {effective_chapters_reviewed}, week index: {r.week_index()}, weekly theme claimed: {r.theme}")

        effective_chapters_reviewed = blitzreview.effective_chapters_reviewed()
        print(f"Effective chapters reviewed for this review: {effective_chapters_reviewed}")

        # The base score is the number of effective chapters reviewed times the base chapter points.
        score = effective_chapters_reviewed * blitz.scoring.chapter_points
        print(f"Base score: {score}")

        # Check how many consecutive chapter intervals we tick over with this review and apply the consecutive chapter bonus.
        if not weekly_theme or weekly_theme.consecutive_chapter_bonus_applies:
            chapter_bonuses = (effective_chapters_reviewed + prev_chapters_reviewed) // blitz.scoring.consecutive_chapter_interval - prev_chapters_reviewed // blitz.scoring.consecutive_chapter_interval
            print(f"Chapter bonuses: {chapter_bonuses}")
            score += chapter_bonuses * blitz.scoring.consecutive_chapter_bonus

        # Apply theme bonuses.
        theme_bonuses_applied = 0

        if weekly_theme:
            theme_bonuses_applied = weekly_theme.claimable_theme_bonuses(form.cleaned_data["satisfies_theme"], blitzreview, prev_reviews)
            if theme_bonuses_applied:
                print(f"Claiming weekly theme {theme_bonuses_applied}x - +{blitz.scoring.theme_bonus * theme_bonuses_applied} points!")
                score += blitz.scoring.theme_bonus * theme_bonuses_applied

        # Apply long chapter bonuses.
        long_chapters = set()
        for chapter in form.cleaned_data["chapter_links"]:
            if chapter.word_count >= blitz.scoring.long_chapter_bonus_words:
                score += blitz.scoring.long_chapter_bonus
                long_chapters.add(chapter)

        # Apply the heat bonus.
        # If we already have a blitzreview, then don't recalculate it - just keep the heat bonus the review had when originally submitted.
        if blitz.scoring.heat_bonus_multiplier:
            if not blitzreview.id:
                heat_bonus = blitzreview.calculate_heat_bonus()
                # Keep track of the heat bonus we got for this review if any, since we won't be able to recalculate it later,
                # and we need to track whether we already received a heat bonus for this author!
                blitzreview.heat_bonus = heat_bonus

            score += blitzreview.heat_bonus

        blitzreview.theme = form.cleaned_data["satisfies_theme"] and theme_bonuses_applied > 0
        blitzreview.score = score
        blitzreview.approved = False
        blitzreview.save()

        if blitzreview.chapter_links.count():
            blitzreview.chapter_links.all().delete()

        for chapter in long_chapters:
            ReviewChapterLink.objects.create(
                review=blitzreview,
                chapter=chapter
            )

        # If the user hasn't already gotten their own "blitz user" instance,
        # create one now
        BlitzUser.objects.get_or_create(blitz=blitz, member=review.author)

        messages.success(self.request, "Your review has been submitted and is pending approval.")
        return HttpResponseRedirect(reverse("blitz_user"))

    def get_form_kwargs(self):
        kwargs = super(BlitzReviewSubmissionFormView, self).get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        return super().get_context_data(blitz=ReviewBlitz.get_current(), **kwargs)


class BlitzReviewApprovalQueueView(PermissionRequiredMixin, ListView):
    template_name = "blitz_review_approval_queue.html"
    permission_required = "reviewblitz.approve"

    def get_queryset(self):
        return BlitzReview.objects.filter(approved=False, blitz=ReviewBlitz.get_current())

    def post(self, request, *args, **kwargs):
        blitz_review_obj = BlitzReview.objects.get(id=request.POST.get("blitz_review_id"))
        if request.POST.get("valid"):
            blitz_review_obj.approved = True
            set_theme_bonus = request.POST.get("theme")
            if set_theme_bonus != blitz_review_obj.theme:
                # Check how many points checking the theme bonus box is worth for this review.
                weekly_theme = blitz_review_obj.get_theme()
                if weekly_theme:
                    theme_bonus_diff = (
                        weekly_theme.claimable_theme_bonuses(True, blitz_review_obj, [])
                        - weekly_theme.claimable_theme_bonuses(False, blitz_review_obj, [])
                    ) * blitz_review_obj.blitz.scoring.theme_bonus

                    if set_theme_bonus and not blitz_review_obj.theme:
                        # Add theme bonus
                        blitz_review_obj.score += theme_bonus_diff
                        blitz_review_obj.theme = True
                    elif blitz_review_obj.theme and not set_theme_bonus:
                        # Remove theme bonus
                        blitz_review_obj.score -= theme_bonus_diff
                        blitz_review_obj.theme = False
            blitz_review_obj.save()
            messages.success(request, f"{blitz_review_obj.review} was approved.")
        else:
            blitz_review_obj.delete()
            messages.warning(
                request,
                f"{blitz_review_obj.review} was rejected. Please remember to inform {blitz_review_obj.review.author}."
            )
        return HttpResponseRedirect(reverse("blitz_review_approval_queue"))


class BlitzLeaderboardView(ListView):
    template_name = "blitz_leaderboard.html"
    context_object_name = "leaderboard"

    def get_object(self):
        return ReviewBlitz.get_current()

    def get_queryset(self):
        return ReviewBlitz.get_current().get_leaderboard()

    def get_context_data(self, **kwargs):
        return super().get_context_data(blitz=ReviewBlitz.get_current(), **kwargs)


class BlitzUserView(LoginRequiredMixin, TemplateView):
    template_name = "blitz_user.html"

    def get_context_data(self, *args, **kwargs):
        context = super(BlitzUserView, self).get_context_data(*args, **kwargs) 

        # Get user info
        # Any bonuses from prize fulfillment (or other sources)
        # Any points spent for prizes

        user, _ = BlitzUser.objects.get_or_create(blitz=ReviewBlitz.get_current(), member=self.request.user.member)

        try:
            queryset = BlitzReview.objects.filter(blitz=ReviewBlitz.get_current(), review__author=self.request.user.member.user_id).order_by('-review__posted_date')
        except AttributeError:
            # User not verified
            # Query fails because they don't have a user_id
            queryset = BlitzReview.objects.none()

        approved_reviews = queryset.filter(approved=True)
        context['approved_reviews'] = approved_reviews

        approved_score = approved_reviews.aggregate(approved_score=Sum('score')).get('approved_score')
        if approved_score is not None:
            context['approved_score'] = approved_score
        else:
            context['approved_score'] = 0

        # Apply any potential bonus points to get effective score
        print(context['approved_score'])
        print(user.bonus_points)
        context['approved_score'] = context['approved_score'] + user.bonus_points

        # Show prize points available by deducting points spent from total score
        context['prize_points'] = context['approved_score'] - user.points_spent

        pending_reviews = queryset.filter(approved=False)
        context['pending_reviews'] = pending_reviews
        context['pending_score'] = pending_reviews.aggregate(approved_score=Sum('score')).get('approved_score')
        return context


class BlitzHistoryView(ListView):
    template_name = "blitz_history.html"
    context_object_name = "blitzes"

    def get_queryset(self):
        return ReviewBlitz.objects.exclude(pk=ReviewBlitz.get_current().pk)


class BlitzView(DetailView):
    model = ReviewBlitz
    template_name = "blitz.html"
    context_object_name = "blitz"

    def get_context_data(self, **kwargs):
        blitz = self.get_object()

        if self.request.user.is_authenticated and self.request.user.member:
            user, _ = BlitzUser.objects.get_or_create(blitz=blitz, member=self.request.user.member)

            try:
                queryset = BlitzReview.objects.filter(blitz=blitz, review__author=self.request.user.member.user_id, approved=True).order_by('-review__posted_date')
            except AttributeError:
                # User not verified
                # Query fails because they don't have a user_id
                queryset = BlitzReview.objects.none()
        else:
            queryset = BlitzReview.objects.none()

        return super().get_context_data(
            user_reviews=queryset,
            leaderboard=self.get_object().get_leaderboard(),
            **kwargs
        )


class HasReviewedView(FormView):
    form_class = HasReviewedForm
    template_name = "has_reviewed.html"

    def get(self, *args, **kwargs):
        form = self.get_form()
        if form.is_bound:
            if form.is_valid():
                return self.form_valid(form)
            else:
                return self.form_invalid(form)
        else:
            return super().get(*args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if 'reviewer' in self.request.GET and 'reviewee' in self.request.GET:
            # Populate the form!
            kwargs.update(data={
                'reviewer': "https://{}members/{}/".format(settings.FORUM_URL, self.request.GET['reviewer']),
                'reviewee': "https://{}members/{}/".format(settings.FORUM_URL, self.request.GET['reviewee'])
            })
        elif self.request.user.is_authenticated and self.request.user.member:
            kwargs.update(initial={
                'reviewer': self.request.user.member.link()
            })
        return kwargs

    def form_valid(self, form):
        reviewer = form.cleaned_data['reviewer'].object
        reviewee = form.cleaned_data['reviewee'].object

        # First, scrape the search results for the author's threads.
        soup = get_soup("https://{}search/member?user_id={}&content=thread".format(settings.FORUM_URL, reviewee.user_id))

        results = []

        threads = []

        def process_results(result_threads):
            for result in result_threads:
                if result.find('div', class_="contentRow-minor").ul.find_all('li')[-1].a['href'] in settings.VALID_FIC_FORUMS:
                    threads.append({'link': forum_url_from_path(result.a['href']), 'title': result.a.contents[-1]})

        process_results(soup.find_all('div', class_="contentRow-main"))

        pagination = soup.find('nav', class_="pageNavWrapper")
        if pagination:
            while nextLink := pagination.find('a', class_="pageNav-jump--next"):
                soup = get_soup(forum_url_from_path(nextLink['href']))

                pagination = soup.find('nav', class_="pageNavWrapper")
                process_results(soup.find_all('div', class_="contentRow-main"))

        for thread in threads:
            soup = get_soup("{}who-replied/?xfFilter[text]={}".format(thread['link'], urllib.parse.quote_plus(reviewer.username)))

            user_list = soup.find('div', class_="userList")
            if user_list:
                # Verify that this really is the correct user.
                for user in user_list.find_all('div', class_="contentRow"):
                    if int(MemberPage.get_params_from_url(user.h3.a['href'])['user_id']) == reviewer.user_id:
                        postcount = user.find('div', class_="whoreplied--postcount").a
                        thread['search'] = forum_url_from_path(postcount['href'])
                        thread['count'] = postcount.text.strip()
                        results.append(thread)
                        break

        return self.render_to_response(self.get_context_data(form=form, reviewer=reviewer, reviewee=reviewee, results=results))

