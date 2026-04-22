"""
MYSTES Tests — Block 6 (Builds #230-232: Trip Posts, Follows, Profiles, Reviews)

Tests for:
- TripPost model (#230): create, to_dict, visibility, referral auto-embed
- TripPhoto model (#230): create, to_dict, position
- TripPost API (#230): CRUD, photos, trip cloning, visibility access control
- UserFollow model (#231): follow/unfollow, unique constraint
- Social API (#231): follow, unfollow, followers/following lists, feed, profile
- ProfileReview model (#232): create, to_dict, verified flag
- Review API (#232): create with booking verification, list, delete, duplicate guard
- Feature flag gating: all flagged endpoints return 403 when disabled

Run: python3 -m pytest tests/test_block6_social.py -v
"""

import json
import sys
import os
import pytest
from datetime import date, datetime, timezone, timedelta

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, 'picasso-sdk'))

from server import app, db, limiter
from models import (
    User, TripPlan, TripMember, TripGuest, ItineraryItem, Booking, Friendship,
    TripPost, TripPhoto, UserFollow, ProfileReview, FeatureFlag,
)


# ───── Fixtures ─────

@pytest.fixture(autouse=True)
def setup_db():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['WTF_CSRF_ENABLED'] = False
    limiter.enabled = False

    with app.app_context():
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client():
    return app.test_client()


def _login_client_as(c, user_id):
    with c.session_transaction() as sess:
        sess['_user_id'] = str(user_id)


def _create_user(email, name='Test User'):
    user = User(email=email, name=name, is_verified=True, is_active=True)
    user.set_password('TestPass1!')
    db.session.add(user)
    db.session.commit()
    return user


def _create_trip(creator_id, name='Test Trip'):
    trip = TripPlan(creator_id=creator_id, name=name, status='draft')
    db.session.add(trip)
    db.session.commit()
    return trip


def _create_item(trip_id, item_type='flight', date_val=None, position=0,
                  search_params=None, external_name=None):
    item = ItineraryItem(
        trip_id=trip_id, item_type=item_type,
        date=date_val, position=position,
        search_params_json=json.dumps(search_params) if search_params else None,
        external_name=external_name,
    )
    db.session.add(item)
    db.session.commit()
    return item


def _enable_flags(*flag_keys):
    for key in flag_keys:
        existing = FeatureFlag.query.filter_by(flag_key=key).first()
        if existing:
            existing.is_enabled = True
        else:
            flag = FeatureFlag(
                flag_key=key, flag_name=key, description='test',
                layer=3, is_enabled=True,
            )
            db.session.add(flag)
    db.session.commit()


# ================================================================
# Part 1: Model Tests
# ================================================================

class TestTripPostModel:
    def test_create_post(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        post = TripPost(
            trip_id=trip.id, user_id=user.id,
            title='My Cancun Trip', visibility='public',
        )
        db.session.add(post)
        db.session.commit()
        assert post.id is not None
        assert post.visibility == 'public'
        assert post.views_count == 0

    def test_post_to_dict(self):
        user = _create_user('u@t.com', 'Alice')
        trip = _create_trip(user.id)
        post = TripPost(
            trip_id=trip.id, user_id=user.id,
            title='Japan 2027', summary_text='Amazing trip',
            tips_json='["Pack light"]', visibility='public',
            referral_code='ALICE-ABC',
        )
        db.session.add(post)
        db.session.commit()
        d = post.to_dict()
        assert d['title'] == 'Japan 2027'
        assert d['author_name'] == 'Alice'
        assert d['tips'] == ['Pack light']
        assert d['referral_code'] == 'ALICE-ABC'

    def test_post_visibility_values(self):
        assert 'public' in TripPost.VISIBILITIES
        assert 'companions_only' in TripPost.VISIBILITIES
        assert 'private' in TripPost.VISIBILITIES


class TestTripPhotoModel:
    def test_create_photo(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        post = TripPost(trip_id=trip.id, user_id=user.id, title='T')
        db.session.add(post)
        db.session.commit()
        photo = TripPhoto(
            trip_post_id=post.id, photo_url='https://img.example.com/1.jpg',
            caption='Sunset', position=1,
        )
        db.session.add(photo)
        db.session.commit()
        assert photo.id is not None

    def test_photo_to_dict(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        post = TripPost(trip_id=trip.id, user_id=user.id, title='T')
        db.session.add(post)
        db.session.commit()
        photo = TripPhoto(
            trip_post_id=post.id, photo_url='https://img.example.com/2.jpg',
            caption='Beach', position=0,
        )
        db.session.add(photo)
        db.session.commit()
        d = photo.to_dict()
        assert d['photo_url'] == 'https://img.example.com/2.jpg'
        assert d['caption'] == 'Beach'


class TestUserFollowModel:
    def test_follow(self):
        u1 = _create_user('a@t.com')
        u2 = _create_user('b@t.com')
        f = UserFollow(follower_user_id=u1.id, followed_user_id=u2.id)
        db.session.add(f)
        db.session.commit()
        assert f.id is not None

    def test_follow_unique(self):
        u1 = _create_user('a@t.com')
        u2 = _create_user('b@t.com')
        f1 = UserFollow(follower_user_id=u1.id, followed_user_id=u2.id)
        db.session.add(f1)
        db.session.commit()
        f2 = UserFollow(follower_user_id=u1.id, followed_user_id=u2.id)
        db.session.add(f2)
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()


class TestProfileReviewModel:
    def test_create_review(self):
        reviewer = _create_user('r@t.com')
        reviewed = _create_user('d@t.com')
        review = ProfileReview(
            reviewer_user_id=reviewer.id,
            reviewed_user_id=reviewed.id,
            rating=5, body='Great travel companion!',
        )
        db.session.add(review)
        db.session.commit()
        assert review.id is not None
        assert review.is_verified_booking is False

    def test_review_to_dict(self):
        reviewer = _create_user('r@t.com', 'Reviewer')
        reviewed = _create_user('d@t.com')
        review = ProfileReview(
            reviewer_user_id=reviewer.id,
            reviewed_user_id=reviewed.id,
            rating=4, body='Good', is_public=True,
        )
        db.session.add(review)
        db.session.commit()
        d = review.to_dict()
        assert d['rating'] == 4
        assert d['reviewer_name'] == 'Reviewer'
        assert d['is_public'] is True


# ================================================================
# Part 2: Feature Flag Gating
# ================================================================

class TestFeatureFlagGating:
    def test_create_post_flag_disabled(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            tid = trip.id
            _login_client_as(client, user.id)
        r = client.post(f'/api/trips/{tid}/posts', json={'title': 'X'})
        assert r.status_code == 403

    def test_follow_flag_disabled(self, client):
        with app.app_context():
            u1 = _create_user('a@t.com')
            u2 = _create_user('b@t.com')
            uid2 = u2.id
            _login_client_as(client, u1.id)
        r = client.post(f'/api/users/{uid2}/follow')
        assert r.status_code == 403

    def test_feed_flag_disabled(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            _login_client_as(client, user.id)
        r = client.get('/api/feed')
        assert r.status_code == 403

    def test_create_review_flag_disabled(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            _login_client_as(client, user.id)
        r = client.post('/api/reviews', json={'reviewed_user_id': 999, 'rating': 5})
        assert r.status_code == 403

    def test_delete_review_flag_disabled(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            _login_client_as(client, user.id)
        r = client.delete('/api/reviews/1')
        assert r.status_code == 403

    def test_new_flags_registered(self):
        FeatureFlag.init_default_flags()
        for key in ('trip_posts', 'social_profiles', 'verified_reviews'):
            flag = FeatureFlag.query.filter_by(flag_key=key).first()
            assert flag is not None
            assert flag.layer == 3
            assert flag.is_enabled is True


# ================================================================
# Part 3: Trip Post CRUD API
# ================================================================

class TestTripPostAPI:
    def test_create_post(self, client):
        with app.app_context():
            _enable_flags('trip_posts')
            user = _create_user('u@t.com')
            user.referral_code = 'USR-ABC'
            db.session.commit()
            trip = _create_trip(user.id)
            tid = trip.id
            _login_client_as(client, user.id)

        r = client.post(f'/api/trips/{tid}/posts', json={
            'title': 'Cancun Recap',
            'summary_text': 'What a trip!',
            'tips': ['Bring sunscreen', 'Book early'],
            'visibility': 'public',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['post']['title'] == 'Cancun Recap'
        assert data['post']['referral_code'] == 'USR-ABC'
        assert len(data['post']['tips']) == 2

    def test_create_post_no_title(self, client):
        with app.app_context():
            _enable_flags('trip_posts')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            tid = trip.id
            _login_client_as(client, user.id)
        r = client.post(f'/api/trips/{tid}/posts', json={})
        assert r.status_code == 400

    def test_list_posts(self, client):
        with app.app_context():
            _enable_flags('trip_posts')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            p1 = TripPost(trip_id=trip.id, user_id=user.id, title='Post 1')
            p2 = TripPost(trip_id=trip.id, user_id=user.id, title='Post 2')
            db.session.add_all([p1, p2])
            db.session.commit()
            tid = trip.id
            _login_client_as(client, user.id)

        r = client.get(f'/api/trips/{tid}/posts')
        assert r.status_code == 200
        assert r.get_json()['count'] == 2

    def test_update_post(self, client):
        with app.app_context():
            _enable_flags('trip_posts')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            post = TripPost(trip_id=trip.id, user_id=user.id, title='Old Title')
            db.session.add(post)
            db.session.commit()
            pid = post.id
            _login_client_as(client, user.id)

        r = client.put(f'/api/posts/{pid}', json={'title': 'New Title', 'visibility': 'private'})
        assert r.status_code == 200
        assert r.get_json()['post']['title'] == 'New Title'
        assert r.get_json()['post']['visibility'] == 'private'

    def test_update_post_not_author(self, client):
        with app.app_context():
            _enable_flags('trip_posts')
            author = _create_user('author@t.com')
            other = _create_user('other@t.com')
            trip = _create_trip(author.id)
            post = TripPost(trip_id=trip.id, user_id=author.id, title='X')
            db.session.add(post)
            db.session.commit()
            pid = post.id
            _login_client_as(client, other.id)

        r = client.put(f'/api/posts/{pid}', json={'title': 'Hacked'})
        assert r.status_code == 403

    def test_delete_post(self, client):
        with app.app_context():
            _enable_flags('trip_posts')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            post = TripPost(trip_id=trip.id, user_id=user.id, title='Delete Me')
            db.session.add(post)
            db.session.commit()
            pid = post.id
            _login_client_as(client, user.id)

        r = client.delete(f'/api/posts/{pid}')
        assert r.status_code == 200
        with app.app_context():
            assert db.session.get(TripPost, pid) is None

    def test_view_public_post_anonymous(self, client):
        """Public posts are viewable without login."""
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            post = TripPost(trip_id=trip.id, user_id=user.id,
                            title='Public Post', visibility='public')
            db.session.add(post)
            db.session.commit()
            pid = post.id

        anon = app.test_client()
        r = anon.get(f'/api/posts/{pid}')
        assert r.status_code == 200
        assert r.get_json()['post']['title'] == 'Public Post'

    def test_view_private_post_denied(self, client):
        """Private posts are only visible to author."""
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            post = TripPost(trip_id=trip.id, user_id=user.id,
                            title='Secret', visibility='private')
            db.session.add(post)
            db.session.commit()
            pid = post.id

        anon = app.test_client()
        r = anon.get(f'/api/posts/{pid}')
        assert r.status_code == 403

    def test_view_increments_counter(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            post = TripPost(trip_id=trip.id, user_id=user.id,
                            title='Views', visibility='public', views_count=0)
            db.session.add(post)
            db.session.commit()
            pid = post.id

        anon = app.test_client()
        anon.get(f'/api/posts/{pid}')
        anon.get(f'/api/posts/{pid}')
        r = anon.get(f'/api/posts/{pid}')
        assert r.get_json()['post']['views_count'] == 3


# ================================================================
# Part 4: Photos API
# ================================================================

class TestPhotosAPI:
    def test_add_photo(self, client):
        with app.app_context():
            _enable_flags('trip_posts')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            post = TripPost(trip_id=trip.id, user_id=user.id, title='T')
            db.session.add(post)
            db.session.commit()
            pid = post.id
            _login_client_as(client, user.id)

        r = client.post(f'/api/posts/{pid}/photos', json={
            'photo_url': 'https://img.example.com/beach.jpg',
            'caption': 'Beach sunset',
        })
        assert r.status_code == 200
        assert r.get_json()['photo']['caption'] == 'Beach sunset'
        assert r.get_json()['photo']['position'] == 1

    def test_add_photo_no_url(self, client):
        with app.app_context():
            _enable_flags('trip_posts')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            post = TripPost(trip_id=trip.id, user_id=user.id, title='T')
            db.session.add(post)
            db.session.commit()
            pid = post.id
            _login_client_as(client, user.id)

        r = client.post(f'/api/posts/{pid}/photos', json={})
        assert r.status_code == 400

    def test_list_photos(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            post = TripPost(trip_id=trip.id, user_id=user.id, title='T')
            db.session.add(post)
            db.session.commit()
            ph1 = TripPhoto(trip_post_id=post.id, photo_url='a.jpg', position=1)
            ph2 = TripPhoto(trip_post_id=post.id, photo_url='b.jpg', position=2)
            db.session.add_all([ph1, ph2])
            db.session.commit()
            pid = post.id

        r = client.get(f'/api/posts/{pid}/photos')
        assert r.status_code == 200
        assert r.get_json()['count'] == 2

    def test_delete_photo(self, client):
        with app.app_context():
            _enable_flags('trip_posts')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            post = TripPost(trip_id=trip.id, user_id=user.id, title='T')
            db.session.add(post)
            db.session.commit()
            photo = TripPhoto(trip_post_id=post.id, photo_url='x.jpg')
            db.session.add(photo)
            db.session.commit()
            pid, phid = post.id, photo.id
            _login_client_as(client, user.id)

        r = client.delete(f'/api/posts/{pid}/photos/{phid}')
        assert r.status_code == 200


# ================================================================
# Part 5: Trip Cloning
# ================================================================

class TestTripCloningAPI:
    def test_clone_trip(self, client):
        with app.app_context():
            _enable_flags('trip_posts')
            author = _create_user('author@t.com')
            trip = _create_trip(author.id, 'Japan Trip')
            _create_item(trip.id, 'flight', date(2027, 6, 5), 0,
                         search_params={'origin': 'LAX', 'destination': 'NRT'})
            _create_item(trip.id, 'hotel', date(2027, 6, 5), 1,
                         external_name='Tokyo Hotel')
            post = TripPost(trip_id=trip.id, user_id=author.id,
                            title='Japan Recap', visibility='public')
            db.session.add(post)
            db.session.commit()
            pid = post.id

            cloner = _create_user('cloner@t.com')
            _login_client_as(client, cloner.id)

        r = client.post(f'/api/posts/{pid}/clone')
        assert r.status_code == 200
        data = r.get_json()
        assert 'cloned' in data['new_trip']['name']
        assert data['items_cloned'] == 2

    def test_clone_private_post_denied(self, client):
        with app.app_context():
            _enable_flags('trip_posts')
            author = _create_user('author@t.com')
            trip = _create_trip(author.id)
            post = TripPost(trip_id=trip.id, user_id=author.id,
                            title='Private', visibility='private')
            db.session.add(post)
            db.session.commit()
            pid = post.id

            cloner = _create_user('cloner@t.com')
            _login_client_as(client, cloner.id)

        r = client.post(f'/api/posts/{pid}/clone')
        assert r.status_code == 403


# ================================================================
# Part 6: Follow / Unfollow API
# ================================================================

class TestFollowAPI:
    def test_follow_user(self, client):
        with app.app_context():
            _enable_flags('social_profiles')
            u1 = _create_user('a@t.com', 'Alice')
            u2 = _create_user('b@t.com', 'Bob')
            uid2 = u2.id
            _login_client_as(client, u1.id)

        r = client.post(f'/api/users/{uid2}/follow')
        assert r.status_code == 200
        assert 'Bob' in r.get_json()['message']

    def test_follow_self_rejected(self, client):
        with app.app_context():
            _enable_flags('social_profiles')
            user = _create_user('u@t.com')
            uid = user.id
            _login_client_as(client, user.id)

        r = client.post(f'/api/users/{uid}/follow')
        assert r.status_code == 400

    def test_follow_idempotent(self, client):
        with app.app_context():
            _enable_flags('social_profiles')
            u1 = _create_user('a@t.com')
            u2 = _create_user('b@t.com')
            uid2 = u2.id
            _login_client_as(client, u1.id)

        client.post(f'/api/users/{uid2}/follow')
        r = client.post(f'/api/users/{uid2}/follow')
        assert r.status_code == 200
        assert 'Already' in r.get_json()['message']

    def test_unfollow(self, client):
        with app.app_context():
            _enable_flags('social_profiles')
            u1 = _create_user('a@t.com')
            u2 = _create_user('b@t.com')
            uid2 = u2.id
            f = UserFollow(follower_user_id=u1.id, followed_user_id=u2.id)
            db.session.add(f)
            db.session.commit()
            _login_client_as(client, u1.id)

        r = client.delete(f'/api/users/{uid2}/follow')
        assert r.status_code == 200

    def test_unfollow_not_following(self, client):
        with app.app_context():
            _enable_flags('social_profiles')
            u1 = _create_user('a@t.com')
            u2 = _create_user('b@t.com')
            uid2 = u2.id
            _login_client_as(client, u1.id)

        r = client.delete(f'/api/users/{uid2}/follow')
        assert r.status_code == 404

    def test_followers_list(self, client):
        with app.app_context():
            u1 = _create_user('a@t.com', 'Alice')
            u2 = _create_user('b@t.com', 'Bob')
            f = UserFollow(follower_user_id=u1.id, followed_user_id=u2.id)
            db.session.add(f)
            db.session.commit()
            uid2 = u2.id

        r = client.get(f'/api/users/{uid2}/followers')
        assert r.status_code == 200
        data = r.get_json()
        assert data['count'] == 1
        assert data['followers'][0]['name'] == 'Alice'

    def test_following_list(self, client):
        with app.app_context():
            u1 = _create_user('a@t.com', 'Alice')
            u2 = _create_user('b@t.com', 'Bob')
            f = UserFollow(follower_user_id=u1.id, followed_user_id=u2.id)
            db.session.add(f)
            db.session.commit()
            uid1 = u1.id

        r = client.get(f'/api/users/{uid1}/following')
        assert r.status_code == 200
        data = r.get_json()
        assert data['count'] == 1
        assert data['following'][0]['name'] == 'Bob'


# ================================================================
# Part 7: Discovery Feed
# ================================================================

class TestDiscoveryFeed:
    def test_feed_shows_followed_posts(self, client):
        with app.app_context():
            _enable_flags('social_profiles')
            alice = _create_user('alice@t.com', 'Alice')
            bob = _create_user('bob@t.com', 'Bob')
            trip = _create_trip(bob.id)
            post = TripPost(trip_id=trip.id, user_id=bob.id,
                            title='Bob Trip', visibility='public')
            db.session.add(post)
            f = UserFollow(follower_user_id=alice.id, followed_user_id=bob.id)
            db.session.add(f)
            db.session.commit()
            _login_client_as(client, alice.id)

        r = client.get('/api/feed')
        assert r.status_code == 200
        data = r.get_json()
        assert data['count'] == 1
        assert data['posts'][0]['title'] == 'Bob Trip'

    def test_feed_empty_no_follows(self, client):
        with app.app_context():
            _enable_flags('social_profiles')
            user = _create_user('u@t.com')
            _login_client_as(client, user.id)

        r = client.get('/api/feed')
        assert r.status_code == 200
        assert r.get_json()['count'] == 0

    def test_feed_excludes_private_posts(self, client):
        with app.app_context():
            _enable_flags('social_profiles')
            alice = _create_user('alice@t.com')
            bob = _create_user('bob@t.com')
            trip = _create_trip(bob.id)
            post = TripPost(trip_id=trip.id, user_id=bob.id,
                            title='Private', visibility='private')
            db.session.add(post)
            f = UserFollow(follower_user_id=alice.id, followed_user_id=bob.id)
            db.session.add(f)
            db.session.commit()
            _login_client_as(client, alice.id)

        r = client.get('/api/feed')
        assert r.get_json()['count'] == 0


# ================================================================
# Part 8: Public Profile
# ================================================================

class TestPublicProfile:
    def test_get_profile(self, client):
        with app.app_context():
            user = _create_user('u@t.com', 'Traveler')
            user.referral_code = 'TRV-123'
            trip = _create_trip(user.id)
            db.session.commit()
            uid = user.id

        r = client.get(f'/api/users/{uid}/profile')
        assert r.status_code == 200
        data = r.get_json()['profile']
        assert data['name'] == 'Traveler'
        assert data['referral_code'] == 'TRV-123'
        assert data['stats']['trips_created'] == 1

    def test_profile_not_found(self, client):
        r = client.get('/api/users/9999/profile')
        assert r.status_code == 404

    def test_profile_badges(self, client):
        """User with 5+ trips gets Trip Planner Pro badge."""
        with app.app_context():
            user = _create_user('u@t.com')
            for i in range(6):
                _create_trip(user.id, f'Trip {i}')
            uid = user.id

        r = client.get(f'/api/users/{uid}/profile')
        data = r.get_json()['profile']
        assert 'Trip Planner Pro' in data['badges']

    def test_profile_shows_is_following(self, client):
        with app.app_context():
            u1 = _create_user('a@t.com')
            u2 = _create_user('b@t.com')
            f = UserFollow(follower_user_id=u1.id, followed_user_id=u2.id)
            db.session.add(f)
            db.session.commit()
            uid2 = u2.id
            _login_client_as(client, u1.id)

        r = client.get(f'/api/users/{uid2}/profile')
        assert r.get_json()['profile']['is_following'] is True


# ================================================================
# Part 9: Verified Reviews API
# ================================================================

class TestReviewsAPI:
    def test_create_review(self, client):
        with app.app_context():
            _enable_flags('verified_reviews')
            reviewer = _create_user('r@t.com', 'Reviewer')
            reviewed = _create_user('d@t.com')
            uid = reviewed.id
            _login_client_as(client, reviewer.id)

        r = client.post('/api/reviews', json={
            'reviewed_user_id': uid,
            'rating': 5,
            'body': 'Amazing trip organizer!',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['review']['rating'] == 5
        assert data['review']['is_verified_booking'] is False

    def test_create_review_with_booking(self, client):
        """Review with valid booking_id is marked as verified."""
        with app.app_context():
            _enable_flags('verified_reviews')
            reviewer = _create_user('r@t.com')
            reviewed = _create_user('d@t.com')
            booking = Booking(user_id=reviewer.id, status='completed')
            db.session.add(booking)
            db.session.commit()
            uid, bid = reviewed.id, booking.id
            _login_client_as(client, reviewer.id)

        r = client.post('/api/reviews', json={
            'reviewed_user_id': uid,
            'rating': 4,
            'booking_id': bid,
        })
        assert r.status_code == 200
        assert r.get_json()['review']['is_verified_booking'] is True

    def test_create_review_invalid_rating(self, client):
        with app.app_context():
            _enable_flags('verified_reviews')
            user = _create_user('u@t.com')
            other = _create_user('o@t.com')
            uid = other.id
            _login_client_as(client, user.id)

        r = client.post('/api/reviews', json={
            'reviewed_user_id': uid, 'rating': 6,
        })
        assert r.status_code == 400

    def test_create_review_self_rejected(self, client):
        with app.app_context():
            _enable_flags('verified_reviews')
            user = _create_user('u@t.com')
            uid = user.id
            _login_client_as(client, user.id)

        r = client.post('/api/reviews', json={
            'reviewed_user_id': uid, 'rating': 5,
        })
        assert r.status_code == 400

    def test_duplicate_review_per_booking(self, client):
        """Cannot review same booking twice."""
        with app.app_context():
            _enable_flags('verified_reviews')
            reviewer = _create_user('r@t.com')
            reviewed = _create_user('d@t.com')
            booking = Booking(user_id=reviewer.id, status='completed')
            db.session.add(booking)
            db.session.commit()
            uid, bid = reviewed.id, booking.id

            # First review
            rev = ProfileReview(
                reviewer_user_id=reviewer.id, reviewed_user_id=uid,
                booking_id=bid, rating=5,
            )
            db.session.add(rev)
            db.session.commit()
            _login_client_as(client, reviewer.id)

        r = client.post('/api/reviews', json={
            'reviewed_user_id': uid, 'rating': 3, 'booking_id': bid,
        })
        assert r.status_code == 409

    def test_list_user_reviews(self, client):
        with app.app_context():
            reviewer = _create_user('r@t.com', 'Alice')
            reviewed = _create_user('d@t.com')
            rev = ProfileReview(
                reviewer_user_id=reviewer.id, reviewed_user_id=reviewed.id,
                rating=4, body='Great!', is_public=True,
            )
            db.session.add(rev)
            db.session.commit()
            uid = reviewed.id

        r = client.get(f'/api/users/{uid}/reviews')
        assert r.status_code == 200
        data = r.get_json()
        assert data['count'] == 1
        assert data['reviews'][0]['reviewer_name'] == 'Alice'

    def test_view_single_review(self, client):
        with app.app_context():
            reviewer = _create_user('r@t.com')
            reviewed = _create_user('d@t.com')
            rev = ProfileReview(
                reviewer_user_id=reviewer.id, reviewed_user_id=reviewed.id,
                rating=5, is_public=True,
            )
            db.session.add(rev)
            db.session.commit()
            rid = rev.id

        r = client.get(f'/api/reviews/{rid}')
        assert r.status_code == 200
        assert r.get_json()['review']['rating'] == 5

    def test_delete_own_review(self, client):
        with app.app_context():
            _enable_flags('verified_reviews')
            reviewer = _create_user('r@t.com')
            reviewed = _create_user('d@t.com')
            rev = ProfileReview(
                reviewer_user_id=reviewer.id, reviewed_user_id=reviewed.id,
                rating=3,
            )
            db.session.add(rev)
            db.session.commit()
            rid = rev.id
            _login_client_as(client, reviewer.id)

        r = client.delete(f'/api/reviews/{rid}')
        assert r.status_code == 200

    def test_delete_others_review_denied(self, client):
        with app.app_context():
            _enable_flags('verified_reviews')
            reviewer = _create_user('r@t.com')
            other = _create_user('o@t.com')
            reviewed = _create_user('d@t.com')
            rev = ProfileReview(
                reviewer_user_id=reviewer.id, reviewed_user_id=reviewed.id,
                rating=2,
            )
            db.session.add(rev)
            db.session.commit()
            rid = rev.id
            _login_client_as(client, other.id)

        r = client.delete(f'/api/reviews/{rid}')
        assert r.status_code == 403


# ================================================================
# Part 10: Access Control
# ================================================================

class TestAccessControl:
    def test_unauthenticated_create_post(self, client):
        r = client.post('/api/trips/1/posts', json={'title': 'X'})
        assert r.status_code in (302, 401)

    def test_unauthenticated_follow(self, client):
        r = client.post('/api/users/1/follow')
        assert r.status_code in (302, 401)

    def test_unauthenticated_review(self, client):
        r = client.post('/api/reviews', json={'reviewed_user_id': 1, 'rating': 5})
        assert r.status_code in (302, 401)

    def test_nonmember_cannot_create_post(self, client):
        with app.app_context():
            _enable_flags('trip_posts')
            owner = _create_user('owner@t.com')
            outsider = _create_user('outsider@t.com')
            trip = _create_trip(owner.id)
            tid = trip.id
            _login_client_as(client, outsider.id)

        r = client.post(f'/api/trips/{tid}/posts', json={'title': 'Hack'})
        assert r.status_code == 403
