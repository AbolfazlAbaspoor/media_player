from core import command_helpers, i18n, instagram_api
NAME = 'cr'
ADMIN_ONLY = False
USAGE = 'cr <text>'


def run(ctx):
    bot = ctx["bot"]
    text = " ".join(ctx.get("args", []))
    if not text:
        bot.t.user_message(ctx["uid"], i18n.t("usage_generic", usage=bot.commands["cr"]["usage"]))
        return
    command_helpers.run_instagram_command(
        ctx, NAME, lambda client, reels, pk: instagram_api.comment_reel(client, pk, text),
        target="reel", ok_key="ig_comment_posted", fail_error="comment_failed")
