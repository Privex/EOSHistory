#!/usr/bin/env bash
################################################################
#                                                              #
#              Production runner script for:                   #
#                                                              #
#                  Privex EOS History                          #
#            (C) 2019 Privex Inc.   GNU AGPL v3                #
#                                                              #
#      Privex Site: https://www.privex.io/                     #
#                                                              #
#      Github Repo: https://github.com/Privex/EOSHistory       #
#                                                              #
################################################################


######
# Directory where the script is located, so we can source files regardless of where PWD is
######

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

cd "$DIR"

[[ -f .env ]] && source .env || echo "Warning: No .env file found."

BOLD="$(tput bold)" RED="$(tput setaf 1)" GREEN="$(tput setaf 2)" YELLOW="$(tput setaf 3)" BLUE="$(tput setaf 4)"
MAGENTA="$(tput setaf 5)" CYAN="$(tput setaf 6)" WHITE="$(tput setaf 7)" RESET="$(tput sgr0)"

# easy coloured messages function
# written by @someguy123
function msg () {
    # usage: msg [color] message
    if [[ "$#" -eq 0 ]]; then echo ""; return; fi;
    if [[ "$#" -eq 1 ]]; then
        echo -e "$1"
        return
    fi

    ts="no"
    if [[ "$#" -gt 2 ]] && [[ "$1" == "ts" ]]; then
        ts="yes"
        shift
    fi
    if [[ "$#" -gt 2 ]] && [[ "$1" == "bold" ]]; then
        echo -n "${BOLD}"
        shift
    fi
    [[ "$ts" == "yes" ]] && _msg="[$(date +'%Y-%m-%d %H:%M:%S %Z')] ${@:2}" || _msg="${@:2}"

    case "$1" in
        bold) echo -e "${BOLD}${_msg}${RESET}";;
        [Bb]*) echo -e "${BLUE}${_msg}${RESET}";;
        [Yy]*) echo -e "${YELLOW}${_msg}${RESET}";;
        [Rr]*) echo -e "${RED}${_msg}${RESET}";;
        [Gg]*) echo -e "${GREEN}${_msg}${RESET}";;
        * ) echo -e "${_msg}";;
    esac
}

case "$1" in
    queue|celery)
        msg ts bold green "Starting EOS History Celery Workers"
        pipenv run celery worker -A eoshistory
        ;;
    sync*|block*|cron)
        msg ts bold green "Running sync_blocks management command to import blocks"
        pipenv run ./manage.py sync_blocks
        ;;
    update|upgrade)
        msg ts bold green " >> Updating files from Github"
        git pull
        msg ts bold green " >> Updating Python packages"
        pipenv update
        msg ts bold green " >> Updating NodeJS packages"
        yarn install
        msg ts bold green " >> Re-building frontend JS Vue Components"
        yarn build
        msg ts bold green " >> Migrating the Postgres database"
        pipenv run ./manage.py migrate
        msg ts bold green " +++ Finished"
        echo
        msg bold yellow "Post-update info:"
        msg yellow "Please **become root**, and read the below additional steps to finish your update"

        msg yellow " - You may wish to update your systemd service files in-case there are any changes:"
        msg blue "\t cp -v *.service /etc/systemd/system/"
        msg blue "\t systemctl daemon-reload"

        msg yellow " - Please remember to restart all EOS History services AS ROOT like so:"
        msg blue "\t systemctl restart eoshistory eoshistory-celery"
        ;;
    serve*|runserv*)
        # Override these defaults inside of `.env`
        : ${HOST='127.0.0.1'}
        : ${PORT='8287'}
        : ${GU_WORKERS='4'}    # Number of Gunicorn worker processes

        pipenv run gunicorn -b "${HOST}:${PORT}" -w "$GU_WORKERS" wsgi
        ;;
    *)
        msg bold red "Unknown command.\n"
        msg bold green "Privex EOS History - (C) 2019 Privex Inc."
        msg bold green "    Website: https://www.privex.io/ \n    Source: https://github.com/Privex/EOSHistory\n"
        msg green "Available run.sh commands:\n"
        msg yellow "\t queue - Start the EOS History Celery Workers - processes block imports from sync_blocks"
        msg yellow "\t cron - Synchronise your history database with the EOS blockchain (queue must be running)"
        msg yellow "\t update - Upgrade your Privex EOS History installation"
        msg yellow "\t server - Start the production Gunicorn server"
        msg green "\nAdditional aliases for the above commands:\n"
        msg yellow "\t sync_blocks, blocks, cron - Aliases for 'cron'"
        msg yellow "\t upgrade - Alias for 'update'"
        msg yellow "\t serve, runserver - Alias for 'server'"

        ;;
esac

msg
