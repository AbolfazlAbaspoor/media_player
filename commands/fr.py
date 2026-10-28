from core import command_helpers, instagram_api
NAME = 'fr'
ADMIN_ONLY = False
USAGE = 'fr'


def run(ctx):
    command_helpers.run_instagram_command(
        ctx, NAME, lambda client, reels, pk: instagram_api.follow_user(client, pk),
        target="user", ok_key="ig_user_followed", fail_error="follow_failed")
