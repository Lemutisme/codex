mkdir -p /tmp/pc-bin /tmp/pc-diff
hangs=0
run_side() {
  input=$1; program=$2; out=$3; shift 3
  rm -rf /tmp/pc-case /tmp/pc-home && mkdir -p /tmp/pc-case /tmp/pc-home "$out" || return 90
  if [ -d /pc-base ]; then cp -R /pc-base/. /tmp/pc-case/ || return 90; fi
  if [ -d "$input/fixture" ]; then cp -R "$input/fixture/." /tmp/pc-case/ || return 90; fi
  ln -sfn "$program" /tmp/pc-bin/executable || return 90
  envs=(); if [ -s "$input/env" ]; then mapfile -t envs < "$input/env"; fi
  if [ -f "$input/terminal.json" ]; then
    (cd /tmp/pc-case && env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 TZ=UTC HOME=/tmp/pc-home ${envs[@]+"${envs[@]}"} python3 /pc/terminal.py "$input" "$out" "$CASE_TIMEOUT" /tmp/pc-bin/executable "$@") || return 90
  else
    (cd /tmp/pc-case || exit 90; env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 TZ=UTC HOME=/tmp/pc-home ${envs[@]+"${envs[@]}"} timeout -k 2 "$CASE_TIMEOUT" /tmp/pc-bin/executable "$@" < "$input/stdin" > "$out/out" 2> "$out/err"; echo $? > "$out/rc") || return 90
  fi
  (cd /tmp/pc-case && find . -type f -print0 | sort -z | xargs -0 -r sha256sum) > "$out/files" 2>/dev/null
}
judge() {
  d=$2; rrc=$(cat "$d/r1/rc")
  if [ "$rrc" = 124 ] || [ "$rrc" = 137 ] || ! cmp -s "$d/r1/rc" "$d/r2/rc"; then printf '@@PC %s unqualified - %s\n' "$1" "$rrc"; return; fi
  stable=''; failed=''
  for ch in rc out err files; do
    if cmp -s "$d/r1/$ch" "$d/r2/$ch"; then
      stable="$stable${stable:+,}$ch"
      cmp -s "$d/r1/$ch" "$d/c/$ch" || failed="$failed $ch"
    fi
  done
  if [ -z "$failed" ]; then printf '@@PC %s pass %s %s\n' "$1" "$stable" "$rrc"; return; fi
  {
    echo "differing channels:$failed"
    echo "exit status: reference $rrc, candidate $(cat "$d/c/rc")"
    for ch in $failed; do
      case $ch in
        out|err) echo "--- $ch (< reference, > candidate)"; diff "$d/r1/$ch" "$d/c/$ch" | head -c 1500; echo ;;
        files) echo '--- files (< reference, > candidate)'; diff "$d/r1/files" "$d/c/files" | head -c 1000; echo ;;
      esac
    done
  } > "$d/report"
  log "$1" "$d/report"
  printf '@@PC %s fail %s %s\n' "$1" "$stable" "$rrc"
}
run_case() {
  step_name=$1; input=$2; d=$3; shift 3
  if [ "$built" != 1 ] || [ "$hangs" -ge "$HANG_BREAKER" ]; then emit "$step_name" blocked; return; fi
  run_side "$input" "$REFERENCE" "$d/r1" "$@" || exit 90
  run_side "$input" "$CANDIDATE" "$d/c" "$@" || exit 90
  case $(cat "$d/c/rc") in 124|137) hangs=$((hangs + 1)) ;; esac
  run_side "$input" "$REFERENCE" "$d/r2" "$@" || exit 90
  judge "$step_name" "$d"
}
obs() { size=$(wc -c < "$2"); if [ "$size" -le "$OBSERVATION_CAP" ]; then cat "$2"; else head -c "$((OBSERVATION_CAP / 2))" "$2"; printf '\n[... %s bytes omitted ...]\n' "$((size - OBSERVATION_CAP))"; tail -c "$((OBSERVATION_CAP / 2))" "$2"; fi | awk -v prefix="$1" '{ print prefix $0 }'; }
observe_case() {
  id=$1; input=$2; d=$3; shift 3
  run_side "$input" "$REFERENCE" "$d/r1" "$@" || exit 90
  run_side "$input" "$REFERENCE" "$d/r2" "$@" || exit 90
  agree=stable; for ch in rc out err files; do cmp -s "$d/r1/$ch" "$d/r2/$ch" || agree=unstable; done
  obs "@@OUT $id " "$d/r1/out"
  obs "@@ERR $id " "$d/r1/err"
  printf '@@OBS %s %s %s\n' "$id" "$(cat "$d/r1/rc")" "$agree"
}
