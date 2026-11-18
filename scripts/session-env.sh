#!/bin/sh
# Claude Code SessionStart hook (declared in .claude-plugin/plugin.json).
#
# Copies the API keys saved in this plugin's options (userConfig, kept in the
# OS keychain) into the environment of the commands Claude runs this session,
# where skills/*/scripts/whm.py reads them. It writes only to the session file
# Claude Code provides, prints nothing, sends nothing anywhere, and skips any
# value with a character outside the plain-key set (letters, digits, space and
# _ . - : @ + | = /). No quote, newline, $ or backtick gets through, so a value
# can never leave its single quotes. Colons, @, | and spaces are allowed because
# Jungle Scout keys are "<name>:<key>", DataForSEO logins are emails and Amazon
# refresh tokens start "Atzr|". A key saved here overrides one exported in your
# shell, for this session only.

[ -n "$CLAUDE_ENV_FILE" ] || exit 0

put() {
  [ -n "$2" ] || return 0
  # Delete every allowed character; anything left besides the # sentinel (which
  # also keeps a trailing newline from being dropped by $(...)) rejects it.
  rest=$(printf '%s#' "$2" | LC_ALL=C tr -d 'A-Za-z0-9_.:@+|=/ -')
  [ "$rest" = "#" ] || return 0
  printf "export %s='%s'\n" "$1" "$2" >> "$CLAUDE_ENV_FILE"
}

put WHM_API_KEY "$CLAUDE_PLUGIN_OPTION_WHM_API_KEY"
put KEEPA_API_KEY "$CLAUDE_PLUGIN_OPTION_KEEPA_API_KEY"
put JUNGLESCOUT_API_KEY "$CLAUDE_PLUGIN_OPTION_JUNGLESCOUT_API_KEY"
put DATAFORSEO_LOGIN "$CLAUDE_PLUGIN_OPTION_DATAFORSEO_LOGIN"
put DATAFORSEO_PASSWORD "$CLAUDE_PLUGIN_OPTION_DATAFORSEO_PASSWORD"
put KALODATA_API_KEY "$CLAUDE_PLUGIN_OPTION_KALODATA_API_KEY"
put SIMILARWEB_API_KEY "$CLAUDE_PLUGIN_OPTION_SIMILARWEB_API_KEY"
put AMAZON_ADS_CLIENT_ID "$CLAUDE_PLUGIN_OPTION_AMAZON_ADS_CLIENT_ID"
put AMAZON_ADS_CLIENT_SECRET "$CLAUDE_PLUGIN_OPTION_AMAZON_ADS_CLIENT_SECRET"
put AMAZON_ADS_REFRESH_TOKEN "$CLAUDE_PLUGIN_OPTION_AMAZON_ADS_REFRESH_TOKEN"
put AMAZON_ADS_PROFILE_ID "$CLAUDE_PLUGIN_OPTION_AMAZON_ADS_PROFILE_ID"
put AMAZON_ADS_REGION "$CLAUDE_PLUGIN_OPTION_AMAZON_ADS_REGION"
exit 0
