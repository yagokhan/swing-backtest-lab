#!/usr/bin/env bash
# qswing kağıt-trade servislerini ayakta tut: reboot kalıcılığı + çökme kurtarma.
# Cron'dan çağrılır: @reboot (boot'ta) ve */5 (watchdog). İdempotent — çalışan varsa dokunmaz.
PY=/usr/bin/python3
DIR=/home/gokhan
LOG="$DIR/swing2_out"
mkdir -p "$LOG"
cd "$DIR" || exit 1

ensure() {            # $1=pgrep deseni, $2=log adı, $3...=çalıştırılacak komut
  local pat="$1" name="$2" p; shift 2
  for p in $(pgrep -f "$pat" 2>/dev/null); do
    # yalnız gerçek python3 süreci sayılır (bash/grep eşleşmesi değil)
    [ "$(cat /proc/$p/comm 2>/dev/null)" = "python3" ] && return 0
  done
  echo "$(date '+%F %T') $name DÜŞMÜŞ → başlatılıyor" >> "$LOG/keepalive.log"
  nohup "$@" >> "$LOG/$name.log" 2>&1 &
}

ensure telegram_command_bot.py cmdbot "$PY" "$DIR/telegram_command_bot.py"
ensure paper_dashboard.py    dashboard "$PY" "$DIR/paper_dashboard.py"
# backtest server: kendi dizininden DIRECTORY=__file__ ile çalışır; sadece PORT=8060 gerekir
ensure "swing-backtest-lab/server.py" backtest env PORT=8060 "$PY" "$DIR/swing-backtest-lab/server.py"
