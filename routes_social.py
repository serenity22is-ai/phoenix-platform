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

from flask import request, jsonify
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
