"""
Utility Functions Module
Helper functions for party management, security, and username generation
"""

import secrets
import random
import time
from datetime import datetime


# Word lists for generating random usernames (e.g., 'BraveWolf42')
ADJECTIVES = [
    'Happy', 'Sleepy', 'Brave', 'Clever', 'Swift', 'Mighty', 'Gentle', 'Wise', 'Lucky', 'Bold',
    'Silent', 'Wild', 'Calm', 'Fierce', 'Noble', 'Quick', 'Bright', 'Dark', 'Golden', 'Silver',
    'Ancient', 'Young', 'Mystic', 'Cosmic', 'Thunder', 'Lightning', 'Storm', 'Frost', 'Fire', 'Shadow',
    'Crimson', 'Azure', 'Jade', 'Ruby', 'Diamond', 'Steel', 'Iron', 'Crystal', 'Blazing', 'Frozen',
    'Electric', 'Savage', 'Loyal', 'Royal', 'Stellar', 'Lunar', 'Solar', 'Astral', 'Phantom', 'Spirit',
    'Mighty', 'Mega', 'Super', 'Ultra', 'Hyper', 'Quantum', 'Cyber', 'Ninja', 'Samurai', 'Warrior',
    'Epic', 'Legendary', 'Mythic', 'Sacred', 'Divine', 'Radiant', 'Glowing', 'Shining', 'Sparkling', 'Dazzling'
]

NOUNS = [
    'Panda', 'Tiger', 'Eagle', 'Dolphin', 'Fox', 'Wolf', 'Bear', 'Hawk', 'Lion', 'Owl',
    'Dragon', 'Phoenix', 'Falcon', 'Raven', 'Panther', 'Jaguar', 'Leopard', 'Cheetah', 'Lynx', 'Cougar',
    'Shark', 'Whale', 'Orca', 'Kraken', 'Serpent', 'Viper', 'Cobra', 'Python', 'Anaconda', 'Komodo',
    'Griffin', 'Pegasus', 'Unicorn', 'Chimera', 'Hydra', 'Sphinx', 'Minotaur', 'Centaur', 'Titan', 'Golem',
    'Samurai', 'Ninja', 'Ronin', 'Shogun', 'Sensei', 'Monk', 'Knight', 'Paladin', 'Archer', 'Ranger',
    'Wizard', 'Sorcerer', 'Mage', 'Warlock', 'Shaman', 'Druid', 'Sage', 'Oracle', 'Prophet', 'Mystic',
    'Valkyrie', 'Guardian', 'Sentinel', 'Watcher', 'Protector', 'Defender', 'Champion', 'Hero', 'Legend', 'Warrior',
    'Ghost', 'Specter', 'Wraith', 'Phantom', 'Spirit', 'Shade', 'Reaper', 'Revenant', 'Banshee', 'Demon'
]


def generate_random_username():
    """Generate a random username like 'HappyPanda42' or 'BraveTiger99'"""
    adjective = random.choice(ADJECTIVES)
    noun = random.choice(NOUNS)
    number = random.randint(1, 99)
    return f"{adjective}{noun}{number}"


def generate_party_code(existing_parties):
    """
    Generate a simple 5-character alphanumeric party code.
    Uses uppercase letters and numbers, excluding confusing characters (0, O, 1, I, L).
    Returns codes like: A3B7K, 9XR4P, etc.

    Args:
        existing_parties: Dictionary of existing party IDs to check uniqueness
    """
    # Character set without confusing characters
    chars = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'

    # Keep generating until we find a unique code
    max_attempts = 100
    for _ in range(max_attempts):
        code = ''.join(random.choice(chars) for _ in range(5))
        if code not in existing_parties:
            return code

    # Fallback to longer code if somehow we can't find a unique 5-digit code
    return secrets.token_urlsafe(8)


def generate_hls_token(party_id, sid, hls_tokens, config, logger):
    """
    Generate a time-limited token for HLS stream access

    Args:
        party_id: Party ID
        sid: Socket session ID
        hls_tokens: Dictionary to store tokens
        config: Configuration object
        logger: Logger instance
    """
    if not config.ENABLE_HLS_TOKEN_VALIDATION:
        logger.debug("HLS token generation skipped - validation disabled")
        return None

    token = secrets.token_urlsafe(32)
    expires = time.time() + config.HLS_TOKEN_EXPIRY
    expires_dt = datetime.fromtimestamp(expires).isoformat()

    hls_tokens[token] = {
        'party_id': party_id,
        'sid': sid,
        'expires': expires
    }

    logger.debug(f"Generated HLS token: {token[:16]}... for party={party_id}, sid={sid}, expires={expires_dt}")
    logger.debug(f"Total active tokens: {len(hls_tokens)}")

    # Clean up expired tokens
    cleanup_expired_tokens(hls_tokens, logger)

    return token


def validate_hls_token(token, hls_tokens, watch_parties, config, logger, item_id=None):
    """
    Validate HLS token and return party_id if valid

    Args:
        token: Token string to validate
        hls_tokens: Dictionary of tokens
        watch_parties: Dictionary of active parties
        config: Configuration object
        logger: Logger instance
        item_id: Optional item ID for additional validation
    """
    if not config.ENABLE_HLS_TOKEN_VALIDATION:
        return True  # Token validation disabled

    if not token:
        logger.debug("Token validation failed: No token provided")
        return False

    if token not in hls_tokens:
        logger.debug(f"Token validation failed: Token not found: {token[:16]}...")
        logger.debug(f"Available tokens: {[t[:16] + '...' for t in list(hls_tokens.keys())[:5]]}")
        return False

    token_data = hls_tokens[token]

    # Check if token expired
    if time.time() > token_data['expires']:
        logger.debug(f"Token validation failed: Token expired")
        del hls_tokens[token]
        return False

    # Check if user is still in the party
    party_id = token_data['party_id']
    sid = token_data['sid']

    if party_id not in watch_parties:
        logger.debug(f"Token validation failed: Party {party_id} not found. Available parties: {list(watch_parties.keys())}")
        return False

    if sid not in watch_parties[party_id]['users']:
        logger.debug(f"Token validation failed: User sid {sid} not in party {party_id}. Current user sids: {list(watch_parties[party_id]['users'].keys())}")
        return False

    logger.debug(f"Token validation successful for party {party_id}, user {sid}")
    return True


def cleanup_expired_tokens(hls_tokens, logger):
    """
    Remove expired HLS tokens

    Args:
        hls_tokens: Dictionary of tokens to clean
        logger: Logger instance
    """
    current_time = time.time()
    expired = [token for token, data in hls_tokens.items() if current_time > data['expires']]
    if expired:
        logger.debug(f"Cleaning up {len(expired)} expired HLS tokens")
        for token in expired:
            logger.debug(f"Removed expired token: {token[:16]}... (party={hls_tokens[token]['party_id']}, sid={hls_tokens[token]['sid']})")
            del hls_tokens[token]


def get_user_token(party_id, sid, hls_tokens, config, logger):
    """
    Get existing valid token for user or generate new one

    Args:
        party_id: Party ID
        sid: Socket session ID
        hls_tokens: Dictionary of tokens
        config: Configuration object
        logger: Logger instance
    """
    # Find existing valid token for this user
    for token, data in hls_tokens.items():
        if data['party_id'] == party_id and data['sid'] == sid:
            if time.time() <= data['expires']:
                logger.debug(f"Reusing existing token for party {party_id}, sid {sid}")
                return token

    # Generate new token
    new_token = generate_hls_token(party_id, sid, hls_tokens, config, logger)
    if new_token:
        logger.debug(f"Generated new token for party {party_id}, sid {sid}: {new_token[:16]}...")
    return new_token
