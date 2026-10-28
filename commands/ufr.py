from core import command_helpers, instagram_api
NAME = 'ufr'
ADMIN_ONLY = False
USAGE = 'ufr'


def run(ctx):
    command_helpers.run_instagram_command(
        ctx, NAME, lambda client, reels, pk: instagram_api.unfollow_user(client, pk),
        target="user", ok_key="ig_user_unfollowed", fail_error="unfollow_failed")
