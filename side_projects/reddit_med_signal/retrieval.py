"""Reddit retrieval via PRAW. Posts + comments per V2 retrieval policy."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import praw

from schemas import RawItem

_log = logging.getLogger("reddit_med_signal.retrieval")

# Patterns for second-level reply inclusion (alternative to score threshold)
_FIRST_PERSON = re.compile(r"\b(I|my|me|myself|I'm|I've|I'd)\b", re.IGNORECASE)


def _build_reddit(credentials: dict) -> praw.Reddit:
    return praw.Reddit(
        client_id=credentials["client_id"],
        client_secret=credentials["client_secret"],
        user_agent=credentials["user_agent"],
        timeout=credentials.get("timeout", 30),
    )


def _post_url(subreddit: str, post_id: str) -> str:
    return f"https://reddit.com/r/{subreddit}/comments/{post_id}"


def _comment_url(subreddit: str, post_id: str, comment_id: str) -> str:
    return f"https://reddit.com/r/{subreddit}/comments/{post_id}/_/{comment_id}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _submission_to_raw(submission: praw.models.Submission) -> RawItem:
    return RawItem(
        item_type="post",
        reddit_id=submission.fullname,
        subreddit=str(submission.subreddit),
        url=_post_url(str(submission.subreddit), submission.id),
        author=str(submission.author) if submission.author else None,
        created_utc=submission.created_utc,
        score=submission.score,
        title=submission.title,
        body=submission.selftext or "",
        parent_post_id=None,
        comment_depth=0,
        parent_comment_id=None,
        retrieved_at=_now_iso(),
    )


def _comment_to_raw(
    comment: praw.models.Comment,
    subreddit: str,
    post_id: str,
    depth: int,
    parent_comment_id: str | None,
) -> RawItem:
    return RawItem(
        item_type="comment",
        reddit_id=comment.fullname,
        subreddit=subreddit,
        url=_comment_url(subreddit, post_id, comment.id),
        author=str(comment.author) if comment.author else None,
        created_utc=comment.created_utc,
        score=comment.score,
        title=None,
        body=comment.body or "",
        parent_post_id=f"t3_{post_id}",
        comment_depth=depth,
        parent_comment_id=parent_comment_id,
        retrieved_at=_now_iso(),
    )


def _second_level_qualifies(
    comment: praw.models.Comment,
    min_len: int,
    min_score: int,
    drug_aliases: list[str],
) -> bool:
    """Check if a second-level reply qualifies for inclusion.

    Include if:
      - len >= min_len  OR
      - contains first-person pronoun AND mentions drug/effect-related term
    """
    body = comment.body or ""
    if len(body) >= min_len:
        return True
    if comment.score >= min_score:
        return True
    # Alternative: first-person + drug mention
    body_lower = body.lower()
    if _FIRST_PERSON.search(body):
        for alias in drug_aliases:
            if alias in body_lower:
                return True
    return False


def retrieve(
    aliases: list[str],
    subreddits: list[str],
    cfg: dict,
    credentials: dict,
) -> list[RawItem]:
    """Retrieve posts + comments from Reddit per V2 policy.

    Returns deduplicated list of RawItems, capped at total_raw_item_cap.
    """
    reddit = _build_reddit(credentials)
    retrieval_cfg = cfg.get("retrieval", {})
    max_posts_per_sub = retrieval_cfg.get("max_posts_per_subreddit", 25)
    max_comments_per_post = retrieval_cfg.get("max_comments_per_post", 10)
    max_second_per_comment = retrieval_cfg.get("max_second_level_per_comment", 3)
    second_min_len = retrieval_cfg.get("second_level_min_len", 80)
    second_min_score = retrieval_cfg.get("second_level_min_score", 3)
    time_filter = retrieval_cfg.get("time_filter", "year")
    sort = retrieval_cfg.get("sort", "relevance")
    total_cap = retrieval_cfg.get("total_raw_item_cap", 500)

    seen_ids: set[str] = set()
    items: list[RawItem] = []

    for sub_name in subreddits:
        try:
            subreddit = reddit.subreddit(sub_name)
        except Exception as e:
            _log.warning("Could not access r/%s: %s", sub_name, e)
            continue

        for alias in aliases:
            if len(items) >= total_cap:
                break
            try:
                submissions = subreddit.search(
                    alias, sort=sort, time_filter=time_filter,
                    limit=max_posts_per_sub,
                )
            except Exception as e:
                _log.warning(
                    "Search failed for '%s' in r/%s: %s", alias, sub_name, e
                )
                continue

            for submission in submissions:
                if len(items) >= total_cap:
                    break

                # Emit post
                if submission.fullname not in seen_ids:
                    seen_ids.add(submission.fullname)
                    items.append(_submission_to_raw(submission))

                # Fetch comments (no replace_more)
                try:
                    submission.comment_sort = "best"
                    top_level_comments = list(submission.comments)[:max_comments_per_post]
                except Exception as e:
                    _log.warning(
                        "Comment fetch failed for %s: %s", submission.id, e
                    )
                    continue

                for tl_comment in top_level_comments:
                    if len(items) >= total_cap:
                        break
                    if not hasattr(tl_comment, "body"):
                        continue  # MoreComments object
                    if tl_comment.fullname in seen_ids:
                        continue
                    seen_ids.add(tl_comment.fullname)
                    items.append(_comment_to_raw(
                        tl_comment, sub_name, submission.id,
                        depth=1, parent_comment_id=None,
                    ))

                    # Second-level replies
                    second_count = 0
                    try:
                        replies = list(tl_comment.replies)
                    except Exception:
                        replies = []

                    for reply in replies:
                        if second_count >= max_second_per_comment:
                            break
                        if len(items) >= total_cap:
                            break
                        if not hasattr(reply, "body"):
                            continue
                        if reply.fullname in seen_ids:
                            continue
                        if not _second_level_qualifies(
                            reply, second_min_len, second_min_score, aliases
                        ):
                            continue
                        seen_ids.add(reply.fullname)
                        items.append(_comment_to_raw(
                            reply, sub_name, submission.id,
                            depth=2, parent_comment_id=tl_comment.fullname,
                        ))
                        second_count += 1

    post_count = sum(1 for i in items if i.item_type == "post")
    comment_count = sum(1 for i in items if i.item_type == "comment")
    _log.info(
        "Retrieved %d items (%d posts, %d comments) from %d subreddits",
        len(items), post_count, comment_count, len(subreddits),
    )
    return items
