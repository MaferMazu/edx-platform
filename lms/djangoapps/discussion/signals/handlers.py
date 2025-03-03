"""
Signal handlers related to discussions.
"""


import logging

from django.conf import settings
from django.dispatch import receiver
from opaque_keys.edx.locator import LibraryLocator
from xmodule.modulestore.django import SignalHandler

from lms.djangoapps.discussion import tasks
from openedx.core.djangoapps.django_comment_common import signals
from openedx.core.djangoapps.site_configuration.models import SiteConfiguration
from openedx.core.djangoapps.theming.helpers import get_current_site

log = logging.getLogger(__name__)


ENABLE_FORUM_NOTIFICATIONS_FOR_SITE_KEY = 'enable_forum_notifications'


@receiver(SignalHandler.course_published)
def update_discussions_on_course_publish(sender, course_key, **kwargs):  # pylint: disable=unused-argument
    """
    Catches the signal that a course has been published in the module
    store and creates/updates the corresponding cache entry.
    Ignores publish signals from content libraries.
    """
    if isinstance(course_key, LibraryLocator):
        return

    context = {
        'course_id': str(course_key),
    }
    tasks.update_discussions_map.apply_async(
        args=[context],
        countdown=settings.DISCUSSION_SETTINGS['COURSE_PUBLISH_TASK_DELAY'],
    )


@receiver(signals.comment_created)
def send_discussion_email_notification(sender, user, post, **kwargs):  # lint-amnesty, pylint: disable=missing-function-docstring, unused-argument
    current_site = get_current_site()
    if current_site is None:
        log.info('Discussion: No current site, not sending notification about post: %s.', post.id)
        return

    try:
        if not current_site.configuration.get_value(ENABLE_FORUM_NOTIFICATIONS_FOR_SITE_KEY, False):
            log_message = 'Discussion: notifications not enabled for site: %s. Not sending message about post: %s.'
            log.info(log_message, current_site, post.id)
            return
    except SiteConfiguration.DoesNotExist:
        log_message = 'Discussion: No SiteConfiguration for site %s. Not sending message about post: %s.'
        log.info(log_message, current_site, post.id)
        return

    send_message(post, current_site)


@receiver(signals.comment_flagged)
@receiver(signals.thread_flagged)
def send_reported_content_email_notification(sender, user, post, **kwargs):  # lint-amnesty, pylint: disable=missing-function-docstring, unused-argument
    current_site = get_current_site()
    if current_site is None:
        log.info('Discussion: No current site, not sending notification about post: %s.', post.id)
        return

    try:
        if not current_site.configuration.get_value(ENABLE_FORUM_NOTIFICATIONS_FOR_SITE_KEY, False):
            log_message = 'Discussion: reported content notifications not enabled for site: %s. ' \
                          'Not sending message about post: %s.'
            log.info(log_message, current_site, post.id)
            return
    except SiteConfiguration.DoesNotExist:
        log_message = 'Discussion: No SiteConfiguration for site %s. Not sending message about post: %s.'
        log.info(log_message, current_site, post.id)
        return

    send_message_for_reported_content(user, post, current_site, sender)


def create_message_context(comment, site):
    thread = comment.thread
    return {
        'course_id': str(thread.course_id),
        'comment_id': comment.id,
        'comment_body': comment.body,
        'comment_author_id': comment.user_id,
        'comment_created_at': comment.created_at,  # comment_client models dates are already serialized
        'thread_id': thread.id,
        'thread_title': thread.title,
        'thread_author_id': thread.user_id,
        'thread_created_at': thread.created_at,  # comment_client models dates are already serialized
        'thread_commentable_id': thread.commentable_id,
        'site_id': site.id
    }


def create_message_context_for_reported_content(user, post, site, sender):
    """
    Create message context for reported content.
    """
    context = {
        'user_id': user.id,
        'course_id': str(post.course_id),
        'thread_id': post.thread.id if sender == 'flag_abuse_for_comment' else post.id,
        'title': post.thread.title if sender == 'flag_abuse_for_comment' else post.title,
        'content_type': post.type,
        'content_body': post.body,
        'thread_created_at': post.created_at,
        'thread_commentable_id': post.commentable_id,
        'site_id': site.id,
    }
    return context


def send_message(comment, site):  # lint-amnesty, pylint: disable=missing-function-docstring
    context = create_message_context(comment, site)
    tasks.send_ace_message.apply_async(args=[context])


def send_message_for_reported_content(user, post, site, sender):  # lint-amnesty, pylint: disable=missing-function-docstring
    context = create_message_context_for_reported_content(user, post, site, sender)
    tasks.send_ace_message_for_reported_content.apply_async(args=[context], countdown=120)
