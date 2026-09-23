"""Reading one Bash call the way a shell would tokenise it, for the two `PreToolUse` guards.

`check-issue-reads.py` and `check-issue-writes.py` each
look for a banned command in the text of a Bash call, and each needs the same
three things done to that text first: a heredoc body removed when it is data
and kept when a shell is reading it, comments dropped, and the rest split into
tokens. They are here once so that a fix to one is a fix to both.

The hooks run as scripts from this directory, so a sibling module imports by
name; each adds the directory to `sys.path` itself so that a test loading a hook
by path finds it as well. Standard library only: the harness runs them under the
system interpreter.
"""
import os
import re
import shlex

#: A heredoc body is data being written to a file unless a shell is reading
#: it, and this project's documents quote commands constantly. Group 3 is the
#: body, kept by `commands_only` when the reader is in `SHELLS`.
HEREDOC = re.compile(
    r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1(.*?)^\s*\2\s*$",
    re.DOTALL | re.MULTILINE)

#: Shell punctuation glued to a token with no space.
GLUED = "`(){}[]<>$"

#: Interpreters whose argument is a new command line.
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}

#: What a word may follow for a `#` after it to begin a comment, besides the
#: start of the text and whitespace.
COMMENT_AFTER = ";&|("

#: Shell syntax that comes before a command and is not one, so
#: `if true; then sh <<'EOF'` still names `sh` as the reader.
BEFORE_A_COMMAND = {"then", "do", "else", "elif", "!", "{", "time"}


def tokens(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        # `strip_comments` has already removed the comments, so a `#` that is
        # left is an ordinary word.
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return command.split()


def reader(before: str) -> str:
    """The command a heredoc is fed to, given the text in front of its `<<`.

    That is the first word of the last command on the line, past any leading
    `NAME=value` assignments, or `""` when there is none.
    """
    # A backslash-newline pair outside a comment is deleted before the line is
    # read, so `bash \` newline `<<EOF` still names `bash`. Comments go first
    # and by the same scan as everywhere else: a comment ends at its newline
    # whatever precedes it, so `# note \` newline `bash <<EOF` is a comment and
    # then a `bash` command, and an escaped backslash (`\\` newline) stays.
    before = strip_comments(before, join_lines="\n")
    # A `&` beside a `<` or `>` is a redirection (`2>&1`, `&>`), not a separator.
    last = re.split(r"\n|;|&&|\|\||\||(?<![<>])&(?!>)|\(", before)[-1]
    for token in tokens(last):
        if token in BEFORE_A_COMMAND or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token):
            continue
        return os.path.basename(token.strip(GLUED))
    return ""


def commands_only(command: str) -> str:
    """What the shell would execute: a heredoc body stays when a shell reads it and goes otherwise."""
    def keep(match: re.Match) -> str:
        if reader(command[:match.start()]) in SHELLS:
            return "\n" + match.group(3) + "\n"
        return "\n"
    return HEREDOC.sub(keep, command)


def strip_comments(text: str, join_lines: str | None = None) -> str:
    """`text` without its shell comments, which run from a `#` that begins a word to the end of the line.

    With `join_lines`, each newline outside quotes is replaced by that string,
    so a caller that would otherwise lose the line break to `shlex` sees one
    command per line. A newline inside quotes is left alone: it is the line
    structure of a script argument (`bash -c '# c` newline `git push'`), which
    the caller reads again and strips per line. A backslash-newline pair, outside
    quotes or inside double quotes, is deleted as bash deletes it, so `git \\`
    newline `push` reads as `git push`; inside single quotes it is literal and
    stays. Without `join_lines`, every newline and every backslash stays.

    `shlex` cannot be trusted with them: an apostrophe inside a comment
    (`git push; # it's done`) is read as an unterminated quote and the whole line
    falls back to a split that misses the push. A `#` inside quotes, after a
    backslash or in the middle of a word (`a#b`, `$#`, `${#x}`) is not a
    comment. Text that ends inside an unterminated quote is returned with its
    comments untouched rather than guessed at. With `join_lines`, the text
    before the quote is as scanned, so a backslash-newline there is deleted, and
    the text from the quote on has every newline replaced by `join_lines`.

    Three forms are still read wrongly, and each drops a banned command that
    comes after it, so the guards allow what an unfiltered reading would refuse: a
    `#` inside backticks (``echo `echo #`; gh ...``), where the comment really
    ends at the closing backtick; a `#` inside a parameter expansion
    (`echo ${x:- #foo}; gh ...`); and a backslash-escaped quote inside `$'...'`
    (`echo $'\\' #'; gh ...`), which this scan reads as closing the quote early.
    """
    out = []
    quote = ""
    quote_start = mark = 0
    begins_word = True
    i = 0
    while i < len(text):
        char = text[i]
        if quote:
            if char == "\\" and quote == '"':
                pair = text[i:i + 2]
                # Inside double quotes bash deletes a backslash-newline too.
                if not (join_lines is not None and pair == "\\\n"):
                    out.append(pair)
                i += 2
                continue
            if char == quote:
                quote = ""
        elif char == "\\":
            pair = text[i:i + 2]
            i += 2
            if join_lines is not None and pair == "\\\n":
                # Bash deletes the pair before it splits words, so `git \` newline
                # `push` is `git push`. Whether the next text begins a word is
                # whatever it was before the pair.
                continue
            out.append(pair)
            begins_word = False
            continue
        elif char in "'\"":
            quote = char
            quote_start, mark = i, len(out)
            begins_word = False
        elif char == "#" and begins_word:
            end = text.find("\n", i)
            i = len(text) if end == -1 else end
            continue
        else:
            begins_word = char.isspace() or char in COMMENT_AFTER
            if char == "\n" and join_lines is not None:
                char = join_lines
        out.append(char)
        i += 1
    if quote:
        if join_lines is None:
            return text
        return "".join(out[:mark]) + text[quote_start:].replace("\n", join_lines)
    return "".join(out)
