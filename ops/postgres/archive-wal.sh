#!/bin/sh
set -eu

# PostgreSQL's archive_command is handed three kinds of file, not one:
#
#   00000001000000000000007E                  a 16 MiB WAL segment
#   00000001000000000000007D.00000028.backup  a base-backup history file
#   00000002.history                          a timeline history file
#
# Rejecting the last two is not a safe validation, it is an outage: a failed
# archive_command is retried forever on the *same* file, so the archiver stops
# advancing and no later segment is ever archived. Archiving then dies silently
# at the first base backup, pg_wal grows without bound, and PITR quietly stops
# working while the backup cron keeps reporting success.
#
# Only the segments are worth compressing — they are the 16 MiB objects, and
# the history files are a few hundred bytes each. The small ones are copied
# under their exact names, which is also what `restore_command` asks for.

source_path="${1:?source WAL path is required}"
name="${2:?archived file name is required}"

case "$name" in
    */*|..|.|'')
        echo "refusing an archive name that is not a plain file name: $name" >&2
        exit 1
        ;;
esac

is_segment=no
case "$name" in
    *[!0-9A-F]*) ;;
    *) [ "${#name}" -eq 24 ] && is_segment=yes ;;
esac

case "$name" in
    *.backup|*.history) ;;
    *)
        if [ "$is_segment" = no ]; then
            echo "unrecognised archive file name: $name" >&2
            exit 1
        fi
        ;;
esac

if [ "$is_segment" = yes ]; then
    target="/wal_archive/${name}.gz"
else
    target="/wal_archive/${name}"
fi
[ -f "$target" ] && exit 0

tmp="${target}.tmp.$$"
trap 'rm -f "$tmp"' EXIT HUP INT TERM
if [ "$is_segment" = yes ]; then
    gzip -c -6 "$source_path" >"$tmp"
    gzip -t "$tmp"
else
    cat "$source_path" >"$tmp"
fi
chmod 600 "$tmp"
mv -f "$tmp" "$target"
trap - EXIT HUP INT TERM
