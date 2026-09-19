#!/usr/bin/env bash
input=$(cat)

cwd=$(echo "$input" | jq -r '.workspace.current_dir // .cwd')
model=$(echo "$input" | jq -r '.model.display_name // empty')
used=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
five=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
week=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')

user=$(whoami)
host=$(hostname -s)

# Build PS1-style prefix: bold green user@host, reset, colon, bold blue cwd, reset
prefix=$(printf '\033[01;32m%s@%s\033[00m:\033[01;34m%s\033[00m' "$user" "$host" "$cwd")

# Build suffix from Claude session info
suffix=""
[ -n "$model" ] && suffix="$model"
[ -n "$used" ] && suffix="$suffix ctx:$(printf '%.0f' "$used")%"
quota=""
[ -n "$five" ] && quota="5h:$(printf '%.0f' "$five")%"
[ -n "$week" ] && quota="$quota${quota:+ }7d:$(printf '%.0f' "$week")%"
[ -n "$quota" ] && suffix="$suffix $quota"

if [ -n "$suffix" ]; then
    printf '%s  %s' "$prefix" "$suffix"
else
    printf '%s' "$prefix"
fi
