from core import command_helpers, instagram_api
NAME = 'lr'
ADMIN_ONLY = False
USAGE = 'lr'


def run(ctx):
    command_helpers.run_instagram_command(
        ctx, NAME, lambda client, reels, pk: instagram_api.like_reel(client, pk),
        target="reel", ok_key="ig_reel_liked", fail_error="like_failed")
