"""
Builds #230-232 — Social Layer (Trip Posts, Follows, Public Profiles, Reviews)

All endpoints gated behind FeatureFlag checks (trip_posts, social_profiles,
verified_reviews). Admin enables flags when Phase C launches.

Endpoints:
  Trip Posts (#230):
  - POST   /api/trips/<id>/posts             — create trip post
  - GET    /api/trips/<id>/posts             — list posts for trip
  - GET    /api/posts/<pid>                  — view single post (public)
  - PUT    /api/posts/<pid>                  — update post (author only)
  - DELETE /api/posts/<pid>                  — delete post (author only)
  - POST   /api/posts/<pid>/photos           — add photo to post
  - GET    /api/posts/<pid>/photos           — list photos
  - DELETE /api/posts/<pid>/photos/<phid>    — remove photo
  - POST   /api/posts/<pid>/clone            — clone trip from post

  Social Profiles + Follows (#231):
  - GET    /api/users/<uid>/profile          — public profile + stats
  - POST   /api/users/<uid>/follow           — follow user
  - DELETE /api/users/<uid>/follow           — unfollow user
  - GET    /api/users/<uid>/followers        — list followers
  - GET    /api/users/<uid>/following        — list following
  - GET    /api/feed                         — discovery feed (posts from followed)

  Verified Reviews (#232):
  - POST   /api/reviews                      — create review (booking required)
  - GET    /api/users/<uid>/reviews          — list reviews for user
  - GET    /api/reviews/<rid>                — view single review
  - DELETE /api/reviews/<rid>                — delete own review

Registration: register_social_routes(app, csrf, limiter)
"""

import json
import logging
from datetime import datetime, timezone

from flask import request, jsonify, render_template_string
from flask_login import current_user, login_required

from models import (
    db, FeatureFlag, User, TripPlan, TripMember, TripGuest,
    ItineraryItem, Booking, TripPost, TripPhoto, UserFollow, ProfileReview,
)

logger = logging.getLogger(__name__)


def _utcnow():
    return datetime.now(timezone.utc)


def _check_flag(flag_key):
    """Return error response if flag is disabled, else None."""
    if not FeatureFlag.is_flag_enabled(flag_key):
        return jsonify({
            'status': 'error',
            'error': f'Feature "{flag_key}" is not enabled',
        }), 403
    return None


def _check_trip_access(trip_id, require_edit=False):
    """Verify current user has access to this trip."""
    trip = db.session.get(TripPlan, trip_id)
    if not trip:
        return None, (jsonify({'status': 'error', 'error': 'Trip not found'}), 404)

    if trip.creator_id == current_user.id:
        return trip, None

    member = TripMember.query.filter_by(
        trip_plan_id=trip_id, user_id=current_user.id
    ).first()
    if not member:
        guest = TripGuest.query.filter_by(
            trip_id=trip_id, user_id=current_user.id
        ).first()
        if not guest:
            return None, (jsonify({'status': 'error', 'error': 'Access denied'}), 403)
        if require_edit and guest.role in ('viewer', 'payer'):
            return None, (jsonify({'status': 'error', 'error': 'Edit access required'}), 403)
        return trip, None

    if require_edit and member.role == 'viewer':
        return None, (jsonify({'status': 'error', 'error': 'Edit access required'}), 403)

    return trip, None


# ============================================================
# Page Templates (Social Layer UI)
# ============================================================

SOCIAL_FEED_CONTENT = '''
<style>
    .feed-hero {
        text-align: center;
        padding: 60px 20px 40px;
    }
    .feed-hero h1 {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 2.4rem;
        font-weight: 700;
        color: #fff;
        margin: 0 0 12px;
    }
    .feed-hero p {
        font-family: 'Outfit', sans-serif;
        color: rgba(255,255,255,0.65);
        font-size: 1.05rem;
        max-width: 520px;
        margin: 0 auto;
    }
    .feed-tabs {
        display: flex;
        justify-content: center;
        gap: 12px;
        margin: 28px 0 36px;
    }
    .feed-tab {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.85rem;
        font-weight: 600;
        letter-spacing: 0.6px;
        padding: 10px 24px;
        border-radius: 30px;
        border: 1px solid rgba(255,255,255,0.12);
        background: rgba(255,255,255,0.04);
        color: rgba(255,255,255,0.55);
        cursor: pointer;
        transition: all 0.3s ease;
    }
    .feed-tab:hover {
        background: rgba(255,255,255,0.08);
        color: rgba(255,255,255,0.85);
    }
    .feed-tab.active {
        background: linear-gradient(135deg, #14b8a6, #0d9488);
        color: #fff;
        border-color: transparent;
    }
    .feed-grid {
        max-width: 960px;
        margin: 0 auto;
        padding: 0 20px 60px;
        columns: 2;
        column-gap: 20px;
    }
    @media (max-width: 640px) {
        .feed-grid { columns: 1; }
        .feed-hero h1 { font-size: 1.8rem; }
    }
    .post-card {
        break-inside: avoid;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 16px;
        overflow: hidden;
        margin-bottom: 20px;
        backdrop-filter: blur(12px);
        transition: transform 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
        cursor: pointer;
    }
    .post-card:hover {
        transform: translateY(-4px);
        border-color: rgba(20,184,166,0.35);
        box-shadow: 0 12px 40px rgba(20,184,166,0.1);
    }
    .post-card-cover {
        width: 100%;
        height: 180px;
        object-fit: cover;
        display: block;
    }
    .post-card-placeholder {
        width: 100%;
        height: 180px;
        background: linear-gradient(135deg, #1a0a2e 0%, #0d4f4f 100%);
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .post-card-placeholder svg {
        width: 48px;
        height: 48px;
        opacity: 0.25;
    }
    .post-card-body {
        padding: 20px;
    }
    .post-card-dest {
        display: inline-block;
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.7rem;
        font-weight: 600;
        letter-spacing: 1px;
        text-transform: uppercase;
        color: #14b8a6;
        background: rgba(20,184,166,0.12);
        padding: 4px 10px;
        border-radius: 6px;
        margin-bottom: 10px;
    }
    .post-card-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.1rem;
        font-weight: 600;
        color: #fff;
        margin: 0 0 8px;
        line-height: 1.35;
    }
    .post-card-excerpt {
        font-family: 'Outfit', sans-serif;
        font-size: 0.88rem;
        color: rgba(255,255,255,0.55);
        line-height: 1.55;
        margin: 0 0 16px;
        display: -webkit-box;
        -webkit-line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .post-card-meta {
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .post-card-avatar {
        width: 32px;
        height: 32px;
        border-radius: 50%;
        background: linear-gradient(135deg, #7c3aed, #14b8a6);
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.7rem;
        font-weight: 700;
        color: #fff;
        flex-shrink: 0;
    }
    .post-card-author {
        font-family: 'Outfit', sans-serif;
        font-size: 0.82rem;
        color: rgba(255,255,255,0.7);
    }
    .post-card-date {
        font-family: 'Outfit', sans-serif;
        font-size: 0.75rem;
        color: rgba(255,255,255,0.35);
        margin-left: auto;
    }
    .post-card-stats {
        display: flex;
        gap: 16px;
        margin-top: 14px;
        padding-top: 14px;
        border-top: 1px solid rgba(255,255,255,0.06);
    }
    .post-card-stat {
        font-family: 'Outfit', sans-serif;
        font-size: 0.75rem;
        color: rgba(255,255,255,0.4);
        display: flex;
        align-items: center;
        gap: 4px;
    }
    .post-card-stat svg {
        width: 14px;
        height: 14px;
        opacity: 0.5;
    }
    .feed-empty {
        text-align: center;
        padding: 80px 20px;
    }
    .feed-empty-icon {
        font-size: 3.5rem;
        margin-bottom: 20px;
        opacity: 0.2;
    }
    .feed-empty h3 {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.3rem;
        color: #fff;
        margin: 0 0 8px;
    }
    .feed-empty p {
        font-family: 'Outfit', sans-serif;
        color: rgba(255,255,255,0.45);
        font-size: 0.95rem;
    }
    .load-more-wrap {
        text-align: center;
        padding: 20px 0 60px;
    }
    .btn-load-more {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.85rem;
        font-weight: 600;
        letter-spacing: 0.6px;
        padding: 12px 36px;
        border-radius: 30px;
        border: 1px solid rgba(20,184,166,0.35);
        background: rgba(20,184,166,0.08);
        color: #14b8a6;
        cursor: pointer;
        transition: all 0.3s ease;
    }
    .btn-load-more:hover {
        background: rgba(20,184,166,0.18);
        border-color: rgba(20,184,166,0.55);
    }
    .btn-load-more:disabled {
        opacity: 0.4;
        cursor: default;
    }
</style>

<div class="feed-hero">
    <h1>Discover Trips</h1>
    <p>See where the MYSTES community is traveling. Get inspired, clone itineraries, and share your own adventures.</p>
</div>

<div class="feed-tabs">
    <button class="feed-tab active" data-feed="discover" onclick="switchTab(this, 'discover')">DISCOVER</button>
    <button class="feed-tab" data-feed="following" onclick="switchTab(this, 'following')">FOLLOWING</button>
</div>

<div id="feedGrid" class="feed-grid"></div>

<div id="feedEmpty" class="feed-empty" style="display:none;">
    <div class="feed-empty-icon">
        <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.2)" stroke-width="1.5">
            <path d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064"/>
            <circle cx="12" cy="12" r="10"/>
        </svg>
    </div>
    <h3 id="emptyTitle">No posts yet</h3>
    <p id="emptySubtitle">Follow travelers or explore discover to see trip posts here.</p>
</div>

<div id="loadMoreWrap" class="load-more-wrap" style="display:none;">
    <button class="btn-load-more" id="btnLoadMore" onclick="loadMore()">Load More</button>
</div>

<script>
var feedPosts = [];
var feedOffset = 0;
var feedLimit = 20;
var currentFeed = 'discover';
var allLoaded = false;

function switchTab(el, type) {
    var tabs = document.querySelectorAll('.feed-tab');
    for (var i = 0; i < tabs.length; i++) { tabs[i].classList.remove('active'); }
    el.classList.add('active');
    currentFeed = type;
    feedOffset = 0;
    allLoaded = false;
    feedPosts = [];
    document.getElementById('feedGrid').innerHTML = '';
    loadFeed();
}

function loadFeed() {
    var url = currentFeed === 'following'
        ? '/api/feed?limit=' + feedLimit + '&offset=' + feedOffset
        : '/api/social/discover?limit=' + feedLimit + '&offset=' + feedOffset;

    fetch(url, { credentials: 'same-origin' })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        var posts = data.posts || [];
        if (posts.length < feedLimit) { allLoaded = true; }
        feedPosts = feedPosts.concat(posts);
        renderPosts(posts, feedOffset === 0);
        feedOffset += posts.length;
        toggleEmpty(feedPosts.length === 0);
        toggleLoadMore(!allLoaded && feedPosts.length > 0);
    })
    .catch(function() {
        if (feedPosts.length === 0) { toggleEmpty(true); }
    });
}

function renderPosts(posts, clear) {
    var grid = document.getElementById('feedGrid');
    if (clear) { grid.innerHTML = ''; }
    for (var i = 0; i < posts.length; i++) {
        grid.appendChild(buildCard(posts[i]));
    }
}

function buildCard(post) {
    var card = document.createElement('div');
    card.className = 'post-card';
    card.onclick = function() { window.location.href = '/post/' + post.id; };

    var coverHtml = '';
    if (post.cover_photo_url) {
        coverHtml = '<img class="post-card-cover" src="' + escHtml(post.cover_photo_url) + '" alt="" loading="lazy">';
    } else {
        coverHtml = '<div class="post-card-placeholder"><svg viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.3)" stroke-width="1.5"><path d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064"/><circle cx="12" cy="12" r="10"/></svg></div>';
    }

    var initials = getInitials(post.author_name || 'M');
    var dateStr = post.created_at ? formatDate(post.created_at) : '';
    var excerpt = post.summary_text || '';
    if (excerpt.length > 160) { excerpt = excerpt.substring(0, 157) + '...'; }

    var destBadge = '';
    if (post.destination) {
        destBadge = '<span class="post-card-dest">' + escHtml(post.destination) + '</span>';
    }

    card.innerHTML = coverHtml +
        '<div class="post-card-body">' +
            destBadge +
            '<h3 class="post-card-title">' + escHtml(post.title) + '</h3>' +
            (excerpt ? '<p class="post-card-excerpt">' + escHtml(excerpt) + '</p>' : '') +
            '<div class="post-card-meta">' +
                '<div class="post-card-avatar">' + escHtml(initials) + '</div>' +
                '<span class="post-card-author">' + escHtml(post.author_name || 'Traveler') + '</span>' +
                '<span class="post-card-date">' + escHtml(dateStr) + '</span>' +
            '</div>' +
            '<div class="post-card-stats">' +
                '<span class="post-card-stat"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>' + (post.views_count || 0) + '</span>' +
                '<span class="post-card-stat"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>' + (post.clones_count || 0) + '</span>' +
                '<span class="post-card-stat"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>' + (post.photo_count || 0) + '</span>' +
            '</div>' +
        '</div>';

    return card;
}

function toggleEmpty(show) {
    document.getElementById('feedEmpty').style.display = show ? 'block' : 'none';
    if (show && currentFeed === 'following') {
        document.getElementById('emptyTitle').textContent = 'Your feed is empty';
        document.getElementById('emptySubtitle').textContent = 'Follow travelers to see their trip posts here.';
    } else if (show) {
        document.getElementById('emptyTitle').textContent = 'No posts yet';
        document.getElementById('emptySubtitle').textContent = 'Be the first to share a trip on MYSTES.';
    }
}

function toggleLoadMore(show) {
    document.getElementById('loadMoreWrap').style.display = show ? 'block' : 'none';
}

function loadMore() {
    var btn = document.getElementById('btnLoadMore');
    btn.disabled = true;
    btn.textContent = 'Loading...';
    loadFeed();
    setTimeout(function() { btn.disabled = false; btn.textContent = 'Load More'; }, 600);
}

function getInitials(name) {
    if (!name) return 'M';
    var parts = name.trim().split(/\\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    return parts[0][0].toUpperCase();
}

function formatDate(iso) {
    try {
        var d = new Date(iso);
        var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
        return months[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
    } catch(e) { return ''; }
}

function escHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

document.addEventListener('DOMContentLoaded', function() { loadFeed(); });
</script>
'''


PROFILE_PAGE_CONTENT = '''
<style>
    .profile-container {
        max-width: 860px;
        margin: 0 auto;
        padding: 40px 20px 80px;
    }
    .profile-header {
        display: flex;
        align-items: center;
        gap: 28px;
        padding: 36px;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 20px;
        backdrop-filter: blur(12px);
        margin-bottom: 28px;
    }
    @media (max-width: 600px) {
        .profile-header {
            flex-direction: column;
            text-align: center;
            gap: 16px;
            padding: 28px 20px;
        }
    }
    .profile-avatar {
        width: 88px;
        height: 88px;
        border-radius: 50%;
        background: linear-gradient(135deg, #7c3aed, #14b8a6);
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: 'Space Grotesk', sans-serif;
        font-size: 2rem;
        font-weight: 700;
        color: #fff;
        flex-shrink: 0;
    }
    .profile-info {
        flex: 1;
    }
    .profile-name {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.75rem;
        font-weight: 700;
        color: #fff;
        margin: 0 0 6px;
    }
    .profile-member-since {
        font-family: 'Outfit', sans-serif;
        font-size: 0.85rem;
        color: rgba(255,255,255,0.4);
    }
    .profile-actions {
        display: flex;
        gap: 10px;
        flex-shrink: 0;
    }
    .btn-follow {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.82rem;
        font-weight: 600;
        letter-spacing: 0.6px;
        padding: 10px 28px;
        border-radius: 30px;
        border: none;
        cursor: pointer;
        transition: all 0.3s ease;
    }
    .btn-follow-active {
        background: linear-gradient(135deg, #14b8a6, #0d9488);
        color: #fff;
    }
    .btn-follow-active:hover {
        background: linear-gradient(135deg, #0d9488, #0f766e);
    }
    .btn-follow-following {
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.15);
        color: rgba(255,255,255,0.7);
    }
    .btn-follow-following:hover {
        background: rgba(239,68,68,0.12);
        border-color: rgba(239,68,68,0.4);
        color: #ef4444;
    }
    .profile-stats {
        display: grid;
        grid-template-columns: repeat(5, 1fr);
        gap: 12px;
        margin-bottom: 28px;
    }
    @media (max-width: 600px) {
        .profile-stats {
            grid-template-columns: repeat(3, 1fr);
        }
    }
    .stat-card {
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px;
        padding: 18px 12px;
        text-align: center;
        backdrop-filter: blur(12px);
    }
    .stat-value {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.5rem;
        font-weight: 700;
        color: #fff;
    }
    .stat-label {
        font-family: 'Outfit', sans-serif;
        font-size: 0.72rem;
        color: rgba(255,255,255,0.4);
        text-transform: uppercase;
        letter-spacing: 0.8px;
        margin-top: 4px;
    }
    .stat-rating {
        color: #C9A96E;
    }
    .profile-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-bottom: 28px;
    }
    .badge-chip {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.5px;
        padding: 6px 14px;
        border-radius: 20px;
        background: linear-gradient(135deg, rgba(124,58,237,0.15), rgba(20,184,166,0.15));
        border: 1px solid rgba(124,58,237,0.25);
        color: rgba(255,255,255,0.8);
    }
    .profile-section-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.1rem;
        font-weight: 600;
        color: #fff;
        margin: 36px 0 18px;
        padding-bottom: 10px;
        border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .profile-tabs {
        display: flex;
        gap: 8px;
        margin-bottom: 24px;
    }
    .profile-tab {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.8rem;
        font-weight: 600;
        letter-spacing: 0.5px;
        padding: 8px 20px;
        border-radius: 24px;
        border: 1px solid rgba(255,255,255,0.1);
        background: transparent;
        color: rgba(255,255,255,0.5);
        cursor: pointer;
        transition: all 0.3s ease;
    }
    .profile-tab:hover { background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.8); }
    .profile-tab.active {
        background: rgba(20,184,166,0.12);
        border-color: rgba(20,184,166,0.3);
        color: #14b8a6;
    }
    .profile-posts-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 14px;
    }
    @media (max-width: 640px) {
        .profile-posts-grid { grid-template-columns: repeat(2, 1fr); }
    }
    .profile-post-card {
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px;
        overflow: hidden;
        cursor: pointer;
        transition: transform 0.3s ease, border-color 0.3s ease;
    }
    .profile-post-card:hover {
        transform: translateY(-3px);
        border-color: rgba(20,184,166,0.3);
    }
    .profile-post-cover {
        width: 100%;
        height: 140px;
        object-fit: cover;
        display: block;
    }
    .profile-post-placeholder {
        width: 100%;
        height: 140px;
        background: linear-gradient(135deg, #1a0a2e, #0d4f4f);
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .profile-post-info {
        padding: 14px;
    }
    .profile-post-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.88rem;
        font-weight: 600;
        color: #fff;
        margin: 0;
        line-height: 1.3;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .review-card {
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px;
        padding: 20px;
        margin-bottom: 14px;
        backdrop-filter: blur(12px);
    }
    .review-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 12px;
    }
    .review-avatar {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        background: linear-gradient(135deg, #7c3aed, #14b8a6);
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.7rem;
        font-weight: 700;
        color: #fff;
        flex-shrink: 0;
    }
    .review-meta {
        flex: 1;
    }
    .review-author {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.88rem;
        font-weight: 600;
        color: #fff;
    }
    .review-date {
        font-family: 'Outfit', sans-serif;
        font-size: 0.75rem;
        color: rgba(255,255,255,0.35);
    }
    .review-verified {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.65rem;
        font-weight: 600;
        letter-spacing: 0.5px;
        padding: 3px 8px;
        border-radius: 10px;
        background: rgba(20,184,166,0.12);
        color: #14b8a6;
    }
    .review-stars {
        color: #C9A96E;
        font-size: 0.95rem;
        letter-spacing: 2px;
        margin-bottom: 8px;
    }
    .review-body {
        font-family: 'Outfit', sans-serif;
        font-size: 0.9rem;
        color: rgba(255,255,255,0.65);
        line-height: 1.6;
    }
    .profile-empty {
        text-align: center;
        padding: 40px 20px;
        color: rgba(255,255,255,0.35);
        font-family: 'Outfit', sans-serif;
    }
</style>

<div class="profile-container">
    <div class="profile-header" id="profileHeader">
        <div class="profile-avatar" id="profileAvatar">M</div>
        <div class="profile-info">
            <h1 class="profile-name" id="profileName">Loading...</h1>
            <div class="profile-member-since" id="profileSince"></div>
        </div>
        <div class="profile-actions" id="profileActions"></div>
    </div>

    <div class="profile-stats" id="profileStats"></div>

    <div class="profile-badges" id="profileBadges"></div>

    <div class="profile-tabs">
        <button class="profile-tab active" onclick="showProfileTab(this, 'posts')">POSTS</button>
        <button class="profile-tab" onclick="showProfileTab(this, 'reviews')">REVIEWS</button>
    </div>

    <div id="postsSection">
        <div class="profile-posts-grid" id="postsGrid"></div>
        <div class="profile-empty" id="postsEmpty" style="display:none;">No public trip posts yet.</div>
    </div>

    <div id="reviewsSection" style="display:none;">
        <div id="reviewsList"></div>
        <div class="profile-empty" id="reviewsEmpty" style="display:none;">No reviews yet.</div>
    </div>
</div>

<script>
var profileUserId = {{ user_id }};
var profileData = null;

function loadProfile() {
    fetch('/api/users/' + profileUserId + '/profile', { credentials: 'same-origin' })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status !== 'ok') return;
        profileData = data.profile;
        renderProfileHeader(profileData);
        renderStats(profileData.stats);
        renderBadges(profileData.badges);
        renderPosts(profileData.recent_posts);
    });
}

function renderProfileHeader(p) {
    var initials = getInitials(p.name || 'MYSTES');
    document.getElementById('profileAvatar').textContent = initials;
    document.getElementById('profileName').textContent = p.name || 'MYSTES Traveler';
    if (p.member_since) {
        var d = new Date(p.member_since);
        var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
        document.getElementById('profileSince').textContent = 'Member since ' + months[d.getMonth()] + ' ' + d.getFullYear();
    }
    renderFollowButton(p.is_following);
}

function renderFollowButton(isFollowing) {
    var container = document.getElementById('profileActions');
    // Do not show button for own profile
    var currentUserId = {{ current_user_id }};
    if (currentUserId === profileUserId || currentUserId === 0) {
        container.innerHTML = '';
        return;
    }
    var btn = document.createElement('button');
    btn.className = 'btn-follow ' + (isFollowing ? 'btn-follow-following' : 'btn-follow-active');
    btn.textContent = isFollowing ? 'FOLLOWING' : 'FOLLOW';
    btn.onclick = function() { toggleFollow(btn, isFollowing); };
    container.innerHTML = '';
    container.appendChild(btn);
}

function toggleFollow(btn, wasFollowing) {
    var method = wasFollowing ? 'DELETE' : 'POST';
    var csrf = document.querySelector('meta[name="csrf-token"]').content;
    fetch('/api/users/' + profileUserId + '/follow', {
        method: method,
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'ok') {
            renderFollowButton(!wasFollowing);
            loadProfile();
        }
    });
}

function renderStats(s) {
    var container = document.getElementById('profileStats');
    var items = [
        { value: s.trips_created || 0, label: 'Trips' },
        { value: s.followers || 0, label: 'Followers' },
        { value: s.following || 0, label: 'Following' },
        { value: s.reviews || 0, label: 'Reviews' },
        { value: s.avg_rating ? s.avg_rating.toFixed(1) : '--', label: 'Rating', cls: 'stat-rating' },
    ];
    var html = '';
    for (var i = 0; i < items.length; i++) {
        var cls = items[i].cls ? ' ' + items[i].cls : '';
        html += '<div class="stat-card"><div class="stat-value' + cls + '">' + items[i].value + '</div><div class="stat-label">' + items[i].label + '</div></div>';
    }
    container.innerHTML = html;
}

function renderBadges(badges) {
    var container = document.getElementById('profileBadges');
    if (!badges || badges.length === 0) { container.style.display = 'none'; return; }
    var html = '';
    for (var i = 0; i < badges.length; i++) {
        html += '<span class="badge-chip">' + escHtml(badges[i]) + '</span>';
    }
    container.innerHTML = html;
}

function renderPosts(posts) {
    var grid = document.getElementById('postsGrid');
    grid.innerHTML = '';
    if (!posts || posts.length === 0) {
        document.getElementById('postsEmpty').style.display = 'block';
        return;
    }
    document.getElementById('postsEmpty').style.display = 'none';
    for (var i = 0; i < posts.length; i++) {
        var p = posts[i];
        var card = document.createElement('div');
        card.className = 'profile-post-card';
        card.onclick = (function(id) { return function() { window.location.href = '/post/' + id; }; })(p.id);
        var coverHtml = p.cover_photo_url
            ? '<img class="profile-post-cover" src="' + escHtml(p.cover_photo_url) + '" alt="" loading="lazy">'
            : '<div class="profile-post-placeholder"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.2)" stroke-width="1.5"><path d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064"/><circle cx="12" cy="12" r="10"/></svg></div>';
        card.innerHTML = coverHtml + '<div class="profile-post-info"><p class="profile-post-title">' + escHtml(p.title) + '</p></div>';
        grid.appendChild(card);
    }
}

function loadReviews() {
    fetch('/api/users/' + profileUserId + '/reviews', { credentials: 'same-origin' })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        var reviews = data.reviews || [];
        var list = document.getElementById('reviewsList');
        list.innerHTML = '';
        if (reviews.length === 0) {
            document.getElementById('reviewsEmpty').style.display = 'block';
            return;
        }
        document.getElementById('reviewsEmpty').style.display = 'none';
        for (var i = 0; i < reviews.length; i++) {
            list.appendChild(buildReviewCard(reviews[i]));
        }
    });
}

function buildReviewCard(r) {
    var card = document.createElement('div');
    card.className = 'review-card';

    var initials = getInitials(r.reviewer_name || 'M');
    var stars = '';
    for (var s = 0; s < 5; s++) { stars += s < r.rating ? '\u2605' : '\u2606'; }
    var verifiedHtml = r.is_verified_booking ? '<span class="review-verified">VERIFIED</span>' : '';
    var dateStr = r.created_at ? formatDate(r.created_at) : '';

    card.innerHTML =
        '<div class="review-header">' +
            '<div class="review-avatar">' + escHtml(initials) + '</div>' +
            '<div class="review-meta"><div class="review-author">' + escHtml(r.reviewer_name || 'Traveler') + '</div><div class="review-date">' + escHtml(dateStr) + '</div></div>' +
            verifiedHtml +
        '</div>' +
        '<div class="review-stars">' + stars + '</div>' +
        (r.body ? '<div class="review-body">' + escHtml(r.body) + '</div>' : '');

    return card;
}

function showProfileTab(el, tab) {
    var tabs = document.querySelectorAll('.profile-tab');
    for (var i = 0; i < tabs.length; i++) { tabs[i].classList.remove('active'); }
    el.classList.add('active');
    document.getElementById('postsSection').style.display = tab === 'posts' ? 'block' : 'none';
    document.getElementById('reviewsSection').style.display = tab === 'reviews' ? 'block' : 'none';
    if (tab === 'reviews') { loadReviews(); }
}

function getInitials(name) {
    if (!name) return 'M';
    var parts = name.trim().split(/\\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    return parts[0][0].toUpperCase();
}

function formatDate(iso) {
    try {
        var d = new Date(iso);
        var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
        return months[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
    } catch(e) { return ''; }
}

function escHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

document.addEventListener('DOMContentLoaded', function() { loadProfile(); });
</script>
'''


POST_DETAIL_CONTENT = '''
<style>
    .post-detail {
        max-width: 820px;
        margin: 0 auto;
        padding: 0 20px 80px;
    }
    .post-hero-wrap {
        position: relative;
        border-radius: 20px;
        overflow: hidden;
        margin-bottom: 32px;
        margin-top: 20px;
    }
    .post-hero-img {
        width: 100%;
        height: 400px;
        object-fit: cover;
        display: block;
    }
    .post-hero-placeholder {
        width: 100%;
        height: 300px;
        background: linear-gradient(135deg, #1a0a2e 0%, #0d4f4f 50%, #1a0a2e 100%);
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .post-hero-placeholder svg {
        width: 64px;
        height: 64px;
        opacity: 0.15;
    }
    .post-hero-overlay {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        padding: 40px 32px 28px;
        background: linear-gradient(transparent, rgba(0,0,0,0.75));
    }
    .post-hero-dest {
        display: inline-block;
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.7rem;
        font-weight: 600;
        letter-spacing: 1.2px;
        text-transform: uppercase;
        color: #14b8a6;
        background: rgba(20,184,166,0.2);
        padding: 5px 12px;
        border-radius: 8px;
        margin-bottom: 10px;
    }
    .post-hero-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 2rem;
        font-weight: 700;
        color: #fff;
        margin: 0;
        line-height: 1.2;
    }
    @media (max-width: 640px) {
        .post-hero-img { height: 260px; }
        .post-hero-title { font-size: 1.5rem; }
    }
    .post-meta-bar {
        display: flex;
        align-items: center;
        gap: 14px;
        margin-bottom: 32px;
        flex-wrap: wrap;
    }
    .post-meta-avatar {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        background: linear-gradient(135deg, #7c3aed, #14b8a6);
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.8rem;
        font-weight: 700;
        color: #fff;
        flex-shrink: 0;
        cursor: pointer;
        transition: transform 0.2s ease;
    }
    .post-meta-avatar:hover { transform: scale(1.1); }
    .post-meta-author {
        font-family: 'Outfit', sans-serif;
        font-size: 0.95rem;
        color: rgba(255,255,255,0.85);
        cursor: pointer;
    }
    .post-meta-author:hover { color: #14b8a6; }
    .post-meta-date {
        font-family: 'Outfit', sans-serif;
        font-size: 0.82rem;
        color: rgba(255,255,255,0.35);
    }
    .post-meta-stats {
        margin-left: auto;
        display: flex;
        gap: 16px;
    }
    .post-meta-stat {
        font-family: 'Outfit', sans-serif;
        font-size: 0.8rem;
        color: rgba(255,255,255,0.4);
        display: flex;
        align-items: center;
        gap: 5px;
    }
    .post-meta-stat svg {
        width: 16px;
        height: 16px;
        opacity: 0.5;
    }
    .post-body-section {
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 16px;
        padding: 28px;
        margin-bottom: 24px;
        backdrop-filter: blur(12px);
    }
    .post-body-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.82rem;
        font-weight: 600;
        letter-spacing: 0.8px;
        text-transform: uppercase;
        color: rgba(255,255,255,0.45);
        margin: 0 0 14px;
    }
    .post-summary {
        font-family: 'Outfit', sans-serif;
        font-size: 1rem;
        color: rgba(255,255,255,0.75);
        line-height: 1.75;
        white-space: pre-line;
    }
    .post-highlights {
        list-style: none;
        padding: 0;
        margin: 0;
    }
    .post-highlights li {
        font-family: 'Outfit', sans-serif;
        font-size: 0.95rem;
        color: rgba(255,255,255,0.7);
        padding: 10px 0;
        border-bottom: 1px solid rgba(255,255,255,0.04);
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .post-highlights li:last-child { border-bottom: none; }
    .highlight-bullet {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: #14b8a6;
        flex-shrink: 0;
    }
    .post-tips {
        list-style: none;
        padding: 0;
        margin: 0;
    }
    .post-tips li {
        font-family: 'Outfit', sans-serif;
        font-size: 0.93rem;
        color: rgba(255,255,255,0.65);
        padding: 10px 0 10px 20px;
        border-left: 2px solid rgba(201,169,110,0.3);
        margin-bottom: 8px;
    }
    .photo-gallery {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 10px;
        margin-bottom: 24px;
    }
    @media (max-width: 640px) {
        .photo-gallery { grid-template-columns: repeat(2, 1fr); }
    }
    .photo-gallery-item {
        border-radius: 12px;
        overflow: hidden;
        cursor: pointer;
        position: relative;
        transition: transform 0.3s ease;
    }
    .photo-gallery-item:hover { transform: scale(1.02); }
    .photo-gallery-item img {
        width: 100%;
        height: 160px;
        object-fit: cover;
        display: block;
    }
    .photo-caption {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        padding: 20px 10px 8px;
        background: linear-gradient(transparent, rgba(0,0,0,0.7));
        font-family: 'Outfit', sans-serif;
        font-size: 0.75rem;
        color: rgba(255,255,255,0.8);
    }
    .post-actions-bar {
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
    }
    .btn-action {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.82rem;
        font-weight: 600;
        letter-spacing: 0.5px;
        padding: 12px 28px;
        border-radius: 30px;
        border: none;
        cursor: pointer;
        transition: all 0.3s ease;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .btn-clone {
        background: linear-gradient(135deg, #14b8a6, #0d9488);
        color: #fff;
    }
    .btn-clone:hover {
        background: linear-gradient(135deg, #0d9488, #0f766e);
        transform: translateY(-1px);
    }
    .btn-clone:disabled {
        opacity: 0.5;
        cursor: default;
        transform: none;
    }
    .btn-share {
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.12);
        color: rgba(255,255,255,0.7);
    }
    .btn-share:hover {
        background: rgba(255,255,255,0.1);
        color: #fff;
    }
    .toast {
        position: fixed;
        bottom: 30px;
        left: 50%;
        transform: translateX(-50%) translateY(100px);
        background: rgba(20,184,166,0.95);
        color: #fff;
        padding: 12px 28px;
        border-radius: 30px;
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.85rem;
        font-weight: 600;
        z-index: 1000;
        transition: transform 0.4s ease;
        pointer-events: none;
    }
    .toast.show {
        transform: translateX(-50%) translateY(0);
    }

    /* Lightbox */
    .lightbox-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0,0,0,0.92);
        z-index: 9999;
        display: none;
        align-items: center;
        justify-content: center;
        cursor: pointer;
    }
    .lightbox-overlay.open {
        display: flex;
    }
    .lightbox-img {
        max-width: 90vw;
        max-height: 85vh;
        border-radius: 8px;
    }
    .lightbox-caption {
        position: absolute;
        bottom: 24px;
        left: 50%;
        transform: translateX(-50%);
        font-family: 'Outfit', sans-serif;
        font-size: 0.9rem;
        color: rgba(255,255,255,0.8);
        text-align: center;
        max-width: 600px;
    }
    .lightbox-close {
        position: absolute;
        top: 20px;
        right: 24px;
        background: rgba(255,255,255,0.1);
        border: none;
        color: #fff;
        width: 40px;
        height: 40px;
        border-radius: 50%;
        font-size: 1.2rem;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
    }
</style>

<div class="post-detail" id="postDetail">
    <div class="post-hero-wrap" id="heroWrap"></div>

    <div class="post-meta-bar" id="metaBar"></div>

    <div id="summarySection" style="display:none;">
        <div class="post-body-section">
            <div class="post-body-title">About This Trip</div>
            <div class="post-summary" id="postSummary"></div>
        </div>
    </div>

    <div id="highlightsSection" style="display:none;">
        <div class="post-body-section">
            <div class="post-body-title">Highlights</div>
            <ul class="post-highlights" id="highlightsList"></ul>
        </div>
    </div>

    <div id="tipsSection" style="display:none;">
        <div class="post-body-section">
            <div class="post-body-title">Tips</div>
            <ul class="post-tips" id="tipsList"></ul>
        </div>
    </div>

    <div id="gallerySection" style="display:none;">
        <div class="post-body-section" style="background:transparent;border:none;padding:0;">
            <div class="post-body-title" style="padding:0 0 14px;">Photos</div>
            <div class="photo-gallery" id="photoGallery"></div>
        </div>
    </div>

    <div class="post-actions-bar" id="actionsBar"></div>
</div>

<div class="toast" id="toast"></div>
<div class="lightbox-overlay" id="lightbox" onclick="closeLightbox()">
    <button class="lightbox-close" onclick="closeLightbox()">&times;</button>
    <img class="lightbox-img" id="lightboxImg" src="" alt="">
    <div class="lightbox-caption" id="lightboxCaption"></div>
</div>

<script>
var postId = {{ post_id }};
var postData = null;

function loadPost() {
    fetch('/api/posts/' + postId, { credentials: 'same-origin' })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status !== 'ok') return;
        postData = data.post;
        renderHero(postData);
        renderMeta(postData);
        renderBody(postData);
        renderActions(postData);
        loadPhotos();
    });
}

function renderHero(p) {
    var wrap = document.getElementById('heroWrap');
    var imgHtml = '';
    if (p.cover_photo_url) {
        imgHtml = '<img class="post-hero-img" src="' + escHtml(p.cover_photo_url) + '" alt="">';
    } else {
        imgHtml = '<div class="post-hero-placeholder"><svg viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.2)" stroke-width="1.5"><path d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064"/><circle cx="12" cy="12" r="10"/></svg></div>';
    }

    var destBadge = p.destination ? '<span class="post-hero-dest">' + escHtml(p.destination) + '</span>' : '';

    wrap.innerHTML = imgHtml +
        '<div class="post-hero-overlay">' +
            destBadge +
            '<h1 class="post-hero-title">' + escHtml(p.title) + '</h1>' +
        '</div>';
}

function renderMeta(p) {
    var bar = document.getElementById('metaBar');
    var initials = getInitials(p.author_name || 'M');
    var dateStr = p.created_at ? formatDate(p.created_at) : '';

    bar.innerHTML =
        '<div class="post-meta-avatar" onclick="goProfile(' + p.user_id + ')">' + escHtml(initials) + '</div>' +
        '<span class="post-meta-author" onclick="goProfile(' + p.user_id + ')">' + escHtml(p.author_name || 'Traveler') + '</span>' +
        '<span class="post-meta-date">' + escHtml(dateStr) + '</span>' +
        '<div class="post-meta-stats">' +
            '<span class="post-meta-stat"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>' + (p.views_count || 0) + '</span>' +
            '<span class="post-meta-stat"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>' + (p.clones_count || 0) + ' cloned</span>' +
        '</div>';
}

function renderBody(p) {
    if (p.summary_text) {
        document.getElementById('summarySection').style.display = 'block';
        document.getElementById('postSummary').textContent = p.summary_text;
    }

    var highlights = p.highlights || [];
    if (highlights.length > 0) {
        document.getElementById('highlightsSection').style.display = 'block';
        var list = document.getElementById('highlightsList');
        list.innerHTML = '';
        for (var i = 0; i < highlights.length; i++) {
            var li = document.createElement('li');
            li.innerHTML = '<span class="highlight-bullet"></span>' + escHtml(String(highlights[i]));
            list.appendChild(li);
        }
    }

    var tips = p.tips || [];
    if (tips.length > 0) {
        document.getElementById('tipsSection').style.display = 'block';
        var tList = document.getElementById('tipsList');
        tList.innerHTML = '';
        for (var j = 0; j < tips.length; j++) {
            var tli = document.createElement('li');
            tli.textContent = tips[j];
            tList.appendChild(tli);
        }
    }
}

function loadPhotos() {
    fetch('/api/posts/' + postId + '/photos', { credentials: 'same-origin' })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        var photos = data.photos || [];
        if (photos.length === 0) return;
        document.getElementById('gallerySection').style.display = 'block';
        var gallery = document.getElementById('photoGallery');
        gallery.innerHTML = '';
        for (var i = 0; i < photos.length; i++) {
            var item = document.createElement('div');
            item.className = 'photo-gallery-item';
            item.onclick = (function(ph) { return function() { openLightbox(ph.photo_url, ph.caption); }; })(photos[i]);
            item.innerHTML = '<img src="' + escHtml(photos[i].thumbnail_url || photos[i].photo_url) + '" alt="" loading="lazy">' +
                (photos[i].caption ? '<div class="photo-caption">' + escHtml(photos[i].caption) + '</div>' : '');
            gallery.appendChild(item);
        }
    });
}

function renderActions(p) {
    var bar = document.getElementById('actionsBar');
    bar.innerHTML =
        '<button class="btn-action btn-clone" id="btnClone" onclick="cloneTrip()"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>Clone This Trip</button>' +
        '<button class="btn-action btn-share" onclick="sharePost()"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>Share</button>';
}

function cloneTrip() {
    var btn = document.getElementById('btnClone');
    btn.disabled = true;
    btn.textContent = 'Cloning...';
    var csrf = document.querySelector('meta[name="csrf-token"]').content;
    fetch('/api/posts/' + postId + '/clone', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'ok') {
            showToast('Trip cloned! Check your Trip Planner.');
            btn.textContent = 'Cloned!';
        } else {
            showToast(data.error || 'Could not clone. Sign in first.');
            btn.disabled = false;
            btn.textContent = 'Clone This Trip';
        }
    })
    .catch(function() {
        btn.disabled = false;
        btn.textContent = 'Clone This Trip';
    });
}

function sharePost() {
    var url = window.location.origin + '/post/' + postId;
    if (navigator.clipboard) {
        navigator.clipboard.writeText(url).then(function() {
            showToast('Link copied to clipboard!');
        });
    } else {
        var inp = document.createElement('input');
        inp.value = url;
        document.body.appendChild(inp);
        inp.select();
        document.execCommand('copy');
        document.body.removeChild(inp);
        showToast('Link copied!');
    }
}

function goProfile(userId) {
    window.location.href = '/profile/' + userId;
}

function openLightbox(src, caption) {
    document.getElementById('lightboxImg').src = src;
    document.getElementById('lightboxCaption').textContent = caption || '';
    document.getElementById('lightbox').classList.add('open');
}

function closeLightbox() {
    document.getElementById('lightbox').classList.remove('open');
}

function showToast(msg) {
    var t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(function() { t.classList.remove('show'); }, 3000);
}

function getInitials(name) {
    if (!name) return 'M';
    var parts = name.trim().split(/\\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    return parts[0][0].toUpperCase();
}

function formatDate(iso) {
    try {
        var d = new Date(iso);
        var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
        return months[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
    } catch(e) { return ''; }
}

function escHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

document.addEventListener('DOMContentLoaded', function() { loadPost(); });
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeLightbox();
});
</script>
'''


def register_social_routes(app, csrf, limiter):
    """Register social layer routes (Builds #230-232)."""

    # ──────────────────────────────────────────────
    # TRIP POSTS (Build #230)
    # ──────────────────────────────────────────────

    @app.route('/api/trips/<int:trip_id>/posts', methods=['POST'])
    @login_required
    def create_trip_post(trip_id):
        """Create a shareable trip post."""
        flag_err = _check_flag('trip_posts')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        data = request.get_json(silent=True) or {}
        title = data.get('title', '').strip()
        if not title:
            return jsonify({'status': 'error', 'error': 'title is required'}), 400

        visibility = data.get('visibility', 'public')
        if visibility not in TripPost.VISIBILITIES:
            visibility = 'public'

        post = TripPost(
            trip_id=trip_id,
            user_id=current_user.id,
            title=title,
            cover_photo_url=data.get('cover_photo_url'),
            summary_text=data.get('summary_text', '').strip() or None,
            highlight_items_json=json.dumps(data.get('highlights', [])),
            tips_json=json.dumps(data.get('tips', [])),
            visibility=visibility,
            show_prices=data.get('show_prices', True),
            referral_code=getattr(current_user, 'referral_code', None),
        )
        db.session.add(post)
        db.session.commit()

        return jsonify({'status': 'ok', 'post': post.to_dict()})

    @app.route('/api/trips/<int:trip_id>/posts', methods=['GET'])
    @login_required
    def list_trip_posts(trip_id):
        """List posts for a trip."""
        flag_err = _check_flag('trip_posts')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        posts = TripPost.query.filter_by(trip_id=trip_id).order_by(
            TripPost.created_at.desc()
        ).all()

        return jsonify({
            'status': 'ok',
            'posts': [p.to_dict() for p in posts],
            'count': len(posts),
        })

    @app.route('/api/posts/<int:post_id>', methods=['GET'])
    def view_trip_post(post_id):
        """View a single trip post (public access for public posts)."""
        post = db.session.get(TripPost, post_id)
        if not post:
            return jsonify({'status': 'error', 'error': 'Post not found'}), 404

        # Access control based on visibility
        if post.visibility == 'private':
            if not current_user.is_authenticated or current_user.id != post.user_id:
                return jsonify({'status': 'error', 'error': 'Post is private'}), 403
        elif post.visibility == 'companions_only':
            if not current_user.is_authenticated:
                return jsonify({'status': 'error', 'error': 'Login required'}), 401
            # Check if viewer is a companion (friend) of author
            from models import Friendship
            is_friend = Friendship.query.filter(
                db.or_(
                    db.and_(Friendship.requester_id == post.user_id,
                            Friendship.addressee_id == current_user.id),
                    db.and_(Friendship.requester_id == current_user.id,
                            Friendship.addressee_id == post.user_id),
                ),
                Friendship.status == 'accepted',
            ).first()
            if not is_friend and current_user.id != post.user_id:
                return jsonify({'status': 'error', 'error': 'Companions only'}), 403

        # Increment view counter
        post.views_count = (post.views_count or 0) + 1
        db.session.commit()

        return jsonify({'status': 'ok', 'post': post.to_dict()})

    @app.route('/api/posts/<int:post_id>', methods=['PUT'])
    @login_required
    def update_trip_post(post_id):
        """Update a trip post (author only)."""
        flag_err = _check_flag('trip_posts')
        if flag_err:
            return flag_err

        post = db.session.get(TripPost, post_id)
        if not post:
            return jsonify({'status': 'error', 'error': 'Post not found'}), 404
        if post.user_id != current_user.id:
            return jsonify({'status': 'error', 'error': 'Only author can update'}), 403

        data = request.get_json(silent=True) or {}
        if 'title' in data:
            title = data['title'].strip()
            if title:
                post.title = title
        if 'summary_text' in data:
            post.summary_text = data['summary_text'].strip() or None
        if 'cover_photo_url' in data:
            post.cover_photo_url = data['cover_photo_url']
        if 'visibility' in data and data['visibility'] in TripPost.VISIBILITIES:
            post.visibility = data['visibility']
        if 'show_prices' in data:
            post.show_prices = bool(data['show_prices'])
        if 'tips' in data:
            post.tips_json = json.dumps(data['tips'])
        if 'highlights' in data:
            post.highlight_items_json = json.dumps(data['highlights'])

        db.session.commit()
        return jsonify({'status': 'ok', 'post': post.to_dict()})

    @app.route('/api/posts/<int:post_id>', methods=['DELETE'])
    @login_required
    def delete_trip_post(post_id):
        """Delete a trip post (author only)."""
        flag_err = _check_flag('trip_posts')
        if flag_err:
            return flag_err

        post = db.session.get(TripPost, post_id)
        if not post:
            return jsonify({'status': 'error', 'error': 'Post not found'}), 404
        if post.user_id != current_user.id:
            return jsonify({'status': 'error', 'error': 'Only author can delete'}), 403

        db.session.delete(post)
        db.session.commit()
        return jsonify({'status': 'ok', 'message': 'Post deleted'})

    # --- Photos ---

    @app.route('/api/posts/<int:post_id>/photos', methods=['POST'])
    @login_required
    def add_post_photo(post_id):
        """Add a photo to a trip post."""
        flag_err = _check_flag('trip_posts')
        if flag_err:
            return flag_err

        post = db.session.get(TripPost, post_id)
        if not post:
            return jsonify({'status': 'error', 'error': 'Post not found'}), 404
        if post.user_id != current_user.id:
            return jsonify({'status': 'error', 'error': 'Only author can add photos'}), 403

        data = request.get_json(silent=True) or {}
        photo_url = data.get('photo_url', '').strip()
        if not photo_url:
            return jsonify({'status': 'error', 'error': 'photo_url is required'}), 400

        max_pos = db.session.query(db.func.max(TripPhoto.position)).filter_by(
            trip_post_id=post_id).scalar() or 0

        photo = TripPhoto(
            trip_post_id=post_id,
            itinerary_item_id=data.get('itinerary_item_id'),
            photo_url=photo_url,
            thumbnail_url=data.get('thumbnail_url'),
            caption=data.get('caption', '').strip() or None,
            uploaded_by_user_id=current_user.id,
            position=max_pos + 1,
        )
        db.session.add(photo)
        db.session.commit()

        return jsonify({'status': 'ok', 'photo': photo.to_dict()})

    @app.route('/api/posts/<int:post_id>/photos', methods=['GET'])
    def list_post_photos(post_id):
        """List photos for a post."""
        post = db.session.get(TripPost, post_id)
        if not post:
            return jsonify({'status': 'error', 'error': 'Post not found'}), 404

        photos = TripPhoto.query.filter_by(trip_post_id=post_id).order_by(
            TripPhoto.position
        ).all()

        return jsonify({
            'status': 'ok',
            'photos': [p.to_dict() for p in photos],
            'count': len(photos),
        })

    @app.route('/api/posts/<int:post_id>/photos/<int:photo_id>', methods=['DELETE'])
    @login_required
    def delete_post_photo(post_id, photo_id):
        """Remove a photo from a post (author only)."""
        flag_err = _check_flag('trip_posts')
        if flag_err:
            return flag_err

        post = db.session.get(TripPost, post_id)
        if not post:
            return jsonify({'status': 'error', 'error': 'Post not found'}), 404
        if post.user_id != current_user.id:
            return jsonify({'status': 'error', 'error': 'Only author can delete photos'}), 403

        photo = db.session.get(TripPhoto, photo_id)
        if not photo or photo.trip_post_id != post_id:
            return jsonify({'status': 'error', 'error': 'Photo not found'}), 404

        db.session.delete(photo)
        db.session.commit()
        return jsonify({'status': 'ok', 'message': 'Photo deleted'})

    # --- Trip Cloning ---

    @app.route('/api/posts/<int:post_id>/clone', methods=['POST'])
    @login_required
    def clone_trip_from_post(post_id):
        """Clone a trip from a public post into the current user's planner."""
        flag_err = _check_flag('trip_posts')
        if flag_err:
            return flag_err

        post = db.session.get(TripPost, post_id)
        if not post:
            return jsonify({'status': 'error', 'error': 'Post not found'}), 404
        if post.visibility == 'private' and post.user_id != current_user.id:
            return jsonify({'status': 'error', 'error': 'Cannot clone private post'}), 403

        # Clone the trip structure
        original_trip = db.session.get(TripPlan, post.trip_id)
        if not original_trip:
            return jsonify({'status': 'error', 'error': 'Original trip not found'}), 404

        new_trip = TripPlan(
            creator_id=current_user.id,
            name=f"{original_trip.name} (cloned)",
            status='draft',
            destinations_json=original_trip.destinations_json,
            is_template=False,
        )
        db.session.add(new_trip)
        db.session.flush()  # get new_trip.id

        # Clone itinerary items (search params, not results)
        items = ItineraryItem.query.filter_by(trip_id=post.trip_id).all()
        for item in items:
            clone = ItineraryItem(
                trip_id=new_trip.id,
                item_type=item.item_type,
                position=item.position,
                date=item.date,
                start_time=item.start_time,
                end_time=item.end_time,
                scope='trip',  # Reset scope to trip-wide
                search_params_json=item.search_params_json,
                external_name=item.external_name,
                external_url=item.external_url,
                notes=item.notes,
                status='suggested',
            )
            db.session.add(clone)

        # Increment clone counter
        post.clones_count = (post.clones_count or 0) + 1
        original_trip.template_copies_count = (original_trip.template_copies_count or 0) + 1
        db.session.commit()

        return jsonify({
            'status': 'ok',
            'new_trip': new_trip.to_dict(),
            'items_cloned': len(items),
        })

    # ──────────────────────────────────────────────
    # SOCIAL PROFILES + FOLLOWS (Build #231)
    # ──────────────────────────────────────────────

    @app.route('/api/users/<int:user_id>/profile', methods=['GET'])
    def get_user_profile(user_id):
        """Public profile with travel stats and badges."""
        user = db.session.get(User, user_id)
        if not user:
            return jsonify({'status': 'error', 'error': 'User not found'}), 404

        # Travel stats — computed from bookings
        booking_count = Booking.query.filter_by(user_id=user_id, status='completed').count()
        total_bookings = Booking.query.filter_by(user_id=user_id).filter(
            Booking.status.in_(['completed', 'booked'])
        ).count()
        trip_count = TripPlan.query.filter_by(creator_id=user_id).count()

        # Post stats
        public_posts = TripPost.query.filter_by(
            user_id=user_id, visibility='public'
        ).order_by(TripPost.created_at.desc()).limit(10).all()

        # Followers / following
        followers_count = UserFollow.query.filter_by(followed_user_id=user_id).count()
        following_count = UserFollow.query.filter_by(follower_user_id=user_id).count()

        # Reviews
        reviews_count = ProfileReview.query.filter_by(
            reviewed_user_id=user_id, is_public=True
        ).count()
        avg_rating = db.session.query(db.func.avg(ProfileReview.rating)).filter_by(
            reviewed_user_id=user_id, is_public=True
        ).scalar()

        # Is current user following?
        is_following = False
        if current_user.is_authenticated and current_user.id != user_id:
            is_following = UserFollow.query.filter_by(
                follower_user_id=current_user.id, followed_user_id=user_id
            ).first() is not None

        # Badges
        badges = []
        if trip_count >= 5:
            badges.append('Trip Planner Pro')
        if booking_count >= 10:
            badges.append('Globe Trotter')
        if total_bookings >= 1:
            badges.append('First Flight')
        if followers_count >= 10:
            badges.append('Social Butterfly')

        return jsonify({
            'status': 'ok',
            'profile': {
                'user_id': user.id,
                'name': user.name,
                'referral_code': user.referral_code,
                'member_since': user.created_at.isoformat() if user.created_at else None,
                'stats': {
                    'trips_created': trip_count,
                    'flights_booked': total_bookings,
                    'completed_bookings': booking_count,
                    'followers': followers_count,
                    'following': following_count,
                    'reviews': reviews_count,
                    'avg_rating': round(avg_rating, 1) if avg_rating else None,
                },
                'badges': badges,
                'is_following': is_following,
                'recent_posts': [p.to_dict() for p in public_posts],
            },
        })

    @app.route('/api/users/<int:user_id>/follow', methods=['POST'])
    @login_required
    def follow_user(user_id):
        """Follow a user."""
        flag_err = _check_flag('social_profiles')
        if flag_err:
            return flag_err

        if current_user.id == user_id:
            return jsonify({'status': 'error', 'error': 'Cannot follow yourself'}), 400

        target = db.session.get(User, user_id)
        if not target:
            return jsonify({'status': 'error', 'error': 'User not found'}), 404

        existing = UserFollow.query.filter_by(
            follower_user_id=current_user.id, followed_user_id=user_id
        ).first()
        if existing:
            return jsonify({'status': 'ok', 'message': 'Already following'})

        follow = UserFollow(
            follower_user_id=current_user.id,
            followed_user_id=user_id,
        )
        db.session.add(follow)
        db.session.commit()

        return jsonify({'status': 'ok', 'message': f'Now following {target.name}'})

    @app.route('/api/users/<int:user_id>/follow', methods=['DELETE'])
    @login_required
    def unfollow_user(user_id):
        """Unfollow a user."""
        flag_err = _check_flag('social_profiles')
        if flag_err:
            return flag_err

        follow = UserFollow.query.filter_by(
            follower_user_id=current_user.id, followed_user_id=user_id
        ).first()
        if not follow:
            return jsonify({'status': 'error', 'error': 'Not following this user'}), 404

        db.session.delete(follow)
        db.session.commit()
        return jsonify({'status': 'ok', 'message': 'Unfollowed'})

    @app.route('/api/users/<int:user_id>/followers', methods=['GET'])
    def list_followers(user_id):
        """List followers of a user."""
        user = db.session.get(User, user_id)
        if not user:
            return jsonify({'status': 'error', 'error': 'User not found'}), 404

        follows = UserFollow.query.filter_by(followed_user_id=user_id).all()
        followers = []
        for f in follows:
            follower = db.session.get(User, f.follower_user_id)
            if follower:
                followers.append({
                    'user_id': follower.id,
                    'name': follower.name,
                    'followed_at': f.created_at.isoformat() if f.created_at else None,
                })

        return jsonify({'status': 'ok', 'followers': followers, 'count': len(followers)})

    @app.route('/api/users/<int:user_id>/following', methods=['GET'])
    def list_following(user_id):
        """List users that a user is following."""
        user = db.session.get(User, user_id)
        if not user:
            return jsonify({'status': 'error', 'error': 'User not found'}), 404

        follows = UserFollow.query.filter_by(follower_user_id=user_id).all()
        following = []
        for f in follows:
            followed = db.session.get(User, f.followed_user_id)
            if followed:
                following.append({
                    'user_id': followed.id,
                    'name': followed.name,
                    'followed_at': f.created_at.isoformat() if f.created_at else None,
                })

        return jsonify({'status': 'ok', 'following': following, 'count': len(following)})

    @app.route('/api/feed', methods=['GET'])
    @login_required
    def discovery_feed():
        """Discovery feed: posts from users you follow, ordered by recency."""
        flag_err = _check_flag('social_profiles')
        if flag_err:
            return flag_err

        # Get IDs of users we follow
        following_ids = [f.followed_user_id for f in
                         UserFollow.query.filter_by(follower_user_id=current_user.id).all()]

        if not following_ids:
            return jsonify({'status': 'ok', 'posts': [], 'count': 0})

        posts = TripPost.query.filter(
            TripPost.user_id.in_(following_ids),
            TripPost.visibility == 'public',
        ).order_by(TripPost.created_at.desc()).limit(50).all()

        return jsonify({
            'status': 'ok',
            'posts': [p.to_dict() for p in posts],
            'count': len(posts),
        })

    # ──────────────────────────────────────────────
    # VERIFIED REVIEWS (Build #232)
    # ──────────────────────────────────────────────

    @app.route('/api/reviews', methods=['POST'])
    @login_required
    def create_review():
        """Create a verified review (booking required for verification)."""
        flag_err = _check_flag('verified_reviews')
        if flag_err:
            return flag_err

        data = request.get_json(silent=True) or {}

        reviewed_user_id = data.get('reviewed_user_id')
        reviewed_account_id = data.get('reviewed_account_id')
        if not reviewed_user_id and not reviewed_account_id:
            return jsonify({'status': 'error', 'error': 'reviewed_user_id or reviewed_account_id required'}), 400

        rating = data.get('rating')
        if not isinstance(rating, int) or rating < 1 or rating > 5:
            return jsonify({'status': 'error', 'error': 'rating must be 1-5'}), 400

        # Cannot review yourself
        if reviewed_user_id and reviewed_user_id == current_user.id:
            return jsonify({'status': 'error', 'error': 'Cannot review yourself'}), 400

        # Booking verification
        booking_id = data.get('booking_id')
        is_verified = False
        if booking_id:
            booking = db.session.get(Booking, booking_id)
            if booking and booking.user_id == current_user.id and booking.status in ('completed', 'booked'):
                is_verified = True
            # Check for duplicate review per booking
            existing = ProfileReview.query.filter_by(
                reviewer_user_id=current_user.id, booking_id=booking_id
            ).first()
            if existing:
                return jsonify({'status': 'error', 'error': 'Already reviewed this booking'}), 409

        review = ProfileReview(
            reviewer_user_id=current_user.id,
            reviewed_user_id=reviewed_user_id,
            reviewed_account_id=reviewed_account_id,
            trip_post_id=data.get('trip_post_id'),
            booking_id=booking_id,
            rating=rating,
            body=data.get('body', '').strip() or None,
            is_verified_booking=is_verified,
            is_public=data.get('is_public', True),
        )
        db.session.add(review)
        db.session.commit()

        return jsonify({'status': 'ok', 'review': review.to_dict()})

    @app.route('/api/users/<int:user_id>/reviews', methods=['GET'])
    def list_user_reviews(user_id):
        """List public reviews for a user."""
        user = db.session.get(User, user_id)
        if not user:
            return jsonify({'status': 'error', 'error': 'User not found'}), 404

        reviews = ProfileReview.query.filter_by(
            reviewed_user_id=user_id, is_public=True
        ).order_by(ProfileReview.created_at.desc()).all()

        return jsonify({
            'status': 'ok',
            'reviews': [r.to_dict() for r in reviews],
            'count': len(reviews),
        })

    @app.route('/api/reviews/<int:review_id>', methods=['GET'])
    def view_review(review_id):
        """View a single review."""
        review = db.session.get(ProfileReview, review_id)
        if not review:
            return jsonify({'status': 'error', 'error': 'Review not found'}), 404
        if not review.is_public:
            if not current_user.is_authenticated or current_user.id != review.reviewer_user_id:
                return jsonify({'status': 'error', 'error': 'Review is not public'}), 403

        return jsonify({'status': 'ok', 'review': review.to_dict()})

    @app.route('/api/reviews/<int:review_id>', methods=['DELETE'])
    @login_required
    def delete_review(review_id):
        """Delete own review."""
        flag_err = _check_flag('verified_reviews')
        if flag_err:
            return flag_err

        review = db.session.get(ProfileReview, review_id)
        if not review:
            return jsonify({'status': 'error', 'error': 'Review not found'}), 404
        if review.reviewer_user_id != current_user.id:
            return jsonify({'status': 'error', 'error': 'Only reviewer can delete'}), 403

        db.session.delete(review)
        db.session.commit()
        return jsonify({'status': 'ok', 'message': 'Review deleted'})

    # ──────────────────────────────────────────────
    # DISCOVER API (public feed for non-following view)
    # ──────────────────────────────────────────────

    @app.route('/api/social/discover', methods=['GET'])
    def social_discover_feed():
        """Public discovery feed: recent public posts from all users."""
        limit = min(int(request.args.get('limit', 20)), 50)
        offset = int(request.args.get('offset', 0))

        posts = TripPost.query.filter_by(
            visibility='public',
        ).order_by(TripPost.created_at.desc()).offset(offset).limit(limit).all()

        return jsonify({
            'status': 'ok',
            'posts': [p.to_dict() for p in posts],
            'count': len(posts),
        })

    # ──────────────────────────────────────────────
    # PAGE ROUTES (Social Layer UI)
    # ──────────────────────────────────────────────

    from server import BASE_TEMPLATE

    @app.route('/social')
    def social_feed_page():
        """Discovery feed page — browse trip posts."""
        return render_template_string(
            BASE_TEMPLATE,
            title='Discover',
            content=SOCIAL_FEED_CONTENT,
        )

    @app.route('/profile/<int:user_id>')
    def public_profile_page(user_id):
        """Public profile page for a user."""
        current_uid = current_user.id if current_user.is_authenticated else 0
        return render_template_string(
            BASE_TEMPLATE,
            title='Profile',
            content=render_template_string(
                PROFILE_PAGE_CONTENT,
                user_id=user_id,
                current_user_id=current_uid,
            ),
        )

    @app.route('/post/<int:post_id>')
    def trip_post_page(post_id):
        """Trip post detail page."""
        return render_template_string(
            BASE_TEMPLATE,
            title='Trip Post',
            content=render_template_string(
                POST_DETAIL_CONTENT,
                post_id=post_id,
            ),
        )
