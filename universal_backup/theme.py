import os,sys
GREEN="\033[92m"; BRIGHT="\033[1;92m"; AMBER="\033[93m"; RED="\033[91m"; RESET="\033[0m"
def paint(s,c=GREEN): return f"{c}{s}{RESET}" if sys.stdout.isatty() and "NO_COLOR" not in os.environ else str(s)
def banner(): print(paint("UNIVERSAL BACKUP // SYSTEM READY",BRIGHT))
