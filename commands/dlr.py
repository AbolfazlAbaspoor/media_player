from core import command_helpers, instagram_api
NAME = 'dlr'
ADMIN_ONLY = False
USAGE = 'dlr'


def run(ctx):
    command_helpers.run_instagram_command(
        ctx, NAME, lambda client, reels, pk: instagram_api.unlike_reel(client, pk),
        target="reel", ok_key="ig_reel_unliked", fail_error="unlike_failed")
