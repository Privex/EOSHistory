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
#
# If you're having problems with this script, you can try using these debugging env vars:
#
#     SG_DEBUG          - Set to 1 to enable verbose debugging messages from this script + Privex ShellCore
#
#     DISABLE_ERR_TRAP  - Set to 1 to disable Privex ShellCore's 'trap.bash' error handler.
#                         The error trap handler detects errors in bash scripts, and allows for cleanly displaying a
#                         traceback + file name + line numbers when errors occur. It also enables various "strict mode"
#                         bash settings, which may cause issues on certain systems and environments. By setting this
#                         to 1, it will not be loaded.
#
# Below is an example showing how to use SG_DEBUG, plus how verbosity SG_DEBUG actually is:
#
#   $ export SG_DEBUG=1
#   $ ./run.sh show_deps
#     ??? _RUN_DIR=/home/x/eoshistory   _hm_shc=/home/x/.pv-shcore     _glb_shc=/usr/local/share/pv-shcore
#     ??? checking if Privex ShellCore is sourced
#     ??? checking if Privex ShellCore is installed locally/globally + auto-install if needed
#     ??? loading Privex ShellCore...
#     (+) Loading cross-platform/shell files from /home/x/.pv-shcore
#        -> Sourcing file /home/x/.pv-shcore/lib/000_gnusafe.sh
#        -> Sourcing file /home/x/.pv-shcore/lib/010_helpers.sh
#     (+) Detected shell 'bash'. Loading bash-specific files.
#
#
######
# Directory where the script is located, so we can source files regardless of where PWD is
######

_RUN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$_RUN_DIR"

[[ -f .env ]] && source .env || echo "Warning: No .env file found."

export PATH="${HOME}/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:${PATH}"

_hm_shc="${HOME}/.pv-shcore" _glb_shc="/usr/local/share/pv-shcore"

_LN="\n------------------------------------------------------------------------------\n"

: ${DEBUGLOG="${_RUN_DIR}/logs/cli_debug.log"}
: ${SG_DEBUG=0}
: ${DISABLE_ERR_TRAP=0}

_tmp_debug() {
    echo "$@" >>"$DEBUGLOG"
    (($SG_DEBUG != 1)) && return
    echo >&2 "$@"
}
_debug() { _tmp_debug "$@"; }

_debug "??? _RUN_DIR=${_RUN_DIR}   _hm_shc=${_hm_shc}     _glb_shc=${_glb_shc}"

_debug "??? checking if Privex ShellCore is sourced"
# Install and/or load Privex ShellCore if it isn't already loaded.
if [ -z ${S_CORE_VER+x} ]; then
    _sc_fail() { echo >&2 "Failed to load or install Privex ShellCore..." && exit 1; } # Error handling function for Privex ShellCore
    # If `load.sh` isn't found in the user install / global install, then download and run the auto-installer from Privex's CDN.
    _debug "??? checking if Privex ShellCore is installed locally/globally + auto-install if needed"

    [[ -f "${_hm_shc}/load.sh" ]] || [[ -f "${_glb_shc}/load.sh" ]] || {
        echo " -> Privex ShellCore not installed...  Please wait while we install it for you :)"
        curl -fsS https://cdn.privex.io/github/shell-core/install.sh | bash >/dev/null
    } || _sc_fail

    _debug "??? loading Privex ShellCore..."
    unset -f _debug # Unset our temporary _debug function, so we can use the shellcore one instead.
    # Attempt to load the local install of ShellCore first, then fallback to global install if it's not found.
    [[ -f "${_hm_shc}/load.sh" ]] && source "${_hm_shc}/load.sh" || source "${_glb_shc}/load.sh" || _sc_fail
fi

# Bash error handler from Privex ShellCore
_debug "??? checking if we should load Privex ShellCore trap error handler..."
((DISABLE_ERR_TRAP == 1)) && _debug "??? DISABLE_ERR_TRAP was 1. not loading trap error handler." || {
    _debug "??? trap error handler is enabled. loading Privex ShellCore trap error handler..."
    source "${SG_DIR}/base/trap.bash"
}

msghr() { msg "${_LN}"; }

# If we don't have sudo, but the user is root, then just create a pass-thru
# sudo function that simply runs the passed commands via env.
_debug "??? checking sudo binary..."
if ! has_binary sudo; then
    if [ "$EUID" -eq 0 ]; then
        sudo() { env "$@"; }
        has_sudo() { return 0; }
    else
        sudo() { return 1; }
        has_sudo() { return 1; }
    fi
else
    has_sudo() { sudo -n ls >/dev/null; }
fi

_debug "??? setting DB_xxxx vars and generating _DB_URL..."
# Override these defaults inside of `.env`
: ${DB_HOST='localhost'}
: ${DB_NAME='eoshistory'}
: ${DB_USER='eoshistory'}
: ${DB_PORT='5432'}
_DB_URL="psql://${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
env_path="${_RUN_DIR}/.env"

: ${PORT='8287'}
: ${GU_WORKERS='4'} # Number of Gunicorn worker processes

# Number of celery workers. If left blank, then celery will run (CPU Cores) workers.
: ${CELERY_WORKERS=''}

_debug "??? DB_HOST=${DB_HOST}   DB_NAME=${DB_NAME}     DB_USER=${DB_USER}    DB_PORT=${DB_PORT}"
_debug "??? _DB_URL=${_DB_URL}   PORT=${PORT}     GU_WORKERS=${GU_WORKERS}    S_CORE_VER=${S_CORE_VER}"

check_pipenv() {
    if ! has_command pipenv; then
        msg ts bold yellow " >>> WARNING: Did not detect pipenv executable. Attempting to install it now."

        if [ "$EUID" -eq 0 ]; then
            pip3 install pipenv
        elif has_sudo; then
            sudo -H pip3 install pipenv
        else
            pip3 install --user pipenv
        fi
        msg ts bold green "\n [+++] Successfully installed pipenv. \n"
    fi
}

has_command() {
    command -v "$1" >/dev/null
}
_debug "??? setting HAS_xxxx vars..."
HAS_PY3='n' HAS_PY37='n' HAS_PIP3='n' HAS_REDIS='n' HAS_RABMQ='n'
TOTAL_DEPS=5 INSTALLED_DEPS=0 HAS_ALLDEPS='n'

scan_deps() {
    _debug "??? [scan_deps] checking if each command is available..."
    has_command python3.7 && HAS_PY37='y' && INSTALLED_DEPS=$((INSTALLED_DEPS + 1))
    has_command python3 && HAS_PY3='y' && INSTALLED_DEPS=$((INSTALLED_DEPS + 1))
    has_command pip3 && HAS_PIP3='y' && INSTALLED_DEPS=$((INSTALLED_DEPS + 1))
    has_command redis-cli && HAS_REDIS='y' && INSTALLED_DEPS=$((INSTALLED_DEPS + 1))
    has_command rabbitmqctl && HAS_RABMQ='y' && INSTALLED_DEPS=$((INSTALLED_DEPS + 1))
    _debug "??? [scan_deps] totalling installed deps..."
    ((INSTALLED_DEPS == TOTAL_DEPS)) && HAS_ALLDEPS='y' || HAS_ALLDEPS='n'
}

_debug "??? calling scan_deps"
scan_deps

print_deps() {
    echo -n "   - python3 "
    [[ "$HAS_PY3" == 'y' ]] && msg green "[YES]" || msg red "[NO]"
    echo -n "   - python3.7 "
    [[ "$HAS_PY37" == 'y' ]] && msg green "[YES]" || msg red "[NO]"
    echo -n "   - python3-pip (pip3) "
    [[ "$HAS_PIP3" == 'y' ]] && msg green "[YES]" || msg red "[NO]"
    echo -n "   - redis "
    [[ "$HAS_REDIS" == 'y' ]] && msg green "[YES]" || msg red "[NO]"
    echo -n "   - rabbitmq-server "
    [[ "$HAS_RABMQ" == 'y' ]] && msg green "[YES]" || msg red "[NO]"
}

install_deps() {
    msg bold green "\n >>> ### Starting EOSHistory Dependency Installer ###\n"
    msg ts cyan "     >>> Running 'apt update' ..."
    sudo apt update -qq -y

    msg ts cyan "     >>> Installing any missing dependencies (e.g. python3.7, redis, rabbitmq etc.) ..."
    msg ts cyan "         >> Installing git ..."
    sudo apt-get install -qq -y git >/dev/null
    msg ts cyan "         >> Installing python3 + python3-pip ..."
    sudo apt-get install -qq -y python3 python3-pip >/dev/null
    msg ts cyan "         >> Installing python3.7 + python3.7-venv ..."
    sudo apt-get install -qq -y python3.7 python3.7-venv python3.7-dev >/dev/null
    msg ts cyan "         >> Installing python3.7-dev ..."
    sudo apt-get install -qq -y python3.7-dev >/dev/null
    msg ts cyan "         >> Installing Redis, libpq-dev (postgres library), and rabbitmq ..."
    sudo apt-get install -qq -y redis-server libpq-dev rabbitmq-server >/dev/null

    msg ts cyan "     >>> Checking if pipenv is installed ..."
    check_pipenv
    msg bold green "\n >>> ### Finished EOSHistory Dependency Installer :) ###\n"

}

check_psql() {
    _debug "??? [check_psql] start of check_psql"
    if ! has_command psql; then
        msg bold yellow " [???] WARNING: Could not detect the executable 'psql'. You need either a local, or " \
            "remote PostgreSQL database server to store the EOSHistory database."
        msg yellow " > If you're planning on using a remote PostgreSQL database (i.e. on a different server), then"
        msg yellow " > you can say 'no' to the following question."
        if yesno "${CYAN}Do you want us to install PostgreSQL for you, using 'apt'? (y/n) > "; then
            msg ts cyan "     >>> Running 'apt update' ..."
            sudo apt update -qq -y
            msg ts cyan "     >>> Installing package 'postgresql' ..."
            sudo apt install -qq -y postgresql
        fi
        msg bold green "\n >>> ### Finished installing PostgreSQL :) ###\n"
    fi
    _debug "??? [check_psql] end of check_psql"
}

# Generate a random password using either openssl (if available), otherwise /dev/urandom + unix utils
# Usage:
#   my_pass=$(gen_pass)
#   my_100_char_pass=$(gen_pass 100)
#
gen_pass() {
    local pass_len=40
    (($# > 0)) && pass_len=$(($1))
    if has_command openssl; then
        openssl rand -hex $((pass_len / 2))
    else
        cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w $((pass_len / 2)) | head -n 1
    fi
}

auto_setup_db() {
    _debug "??? [auto_setup_db] start of auto_setup_db"
    err_sudo() {
        msg red " > Please make sure sudo is installed by running 'apt install sudo' as root, and if you don't want to "
        msg red " > or can't setup passwordless sudo, then you can later run the following command as root: \n"
        msg red "      $0 db_setup \n"
        msg red " > The above command (run as root!) will run only the automated database setup portion of the easy"
        msg red " > installer.\n"
    }
    msg
    msg cyan " >>> If you're running a ${BOLD}local PostgreSQL installation${RESET}${CYAN}, we can automatically"
    msg cyan "     create the database user 'eoshistory', generate + set the user's password, save the password to"
    msg cyan "     your .env file, and create the database 'eoshistory' owned by the 'eoshistory' user."
    msg
    msg yellow " >>> Please note automatic PostgreSQL setup will only work if you haven't made the user 'eoshistory'"
    msg yellow "     nor the database 'eoshistory' yet."
    msg

    if [ "$EUID" -eq 0 ]; then
        _debug "??? user appears to be root. checking if we have the sudo binary."
        if has_binary sudo; then
            _debug "??? system has sudo binary. all good."
        else
            _debug "??? user is root, but sudo is not installed. cannot run commands via postgres user."
            msg bold red " [!!!] Cannot auto-configure your PostgreSQL database. Despite you appearing to be root, "
            msg bold red " [!!!] it seems that the 'sudo' executable isn't installed..."
            err_sudo
            return
        fi
    elif ! has_sudo || ! has_binary sudo; then
        _debug "??? [auto_setup_db] user is NOT root, and has failed 'has_sudo' or 'has_binary sudo'..."
        msg bold red " [!!!] Cannot auto-configure your PostgreSQL database as you aren't root, and you don't have "
        msg bold red " [!!!] passwordless sudo."
        err_sudo
        sleep 5
        msg yellow " > If you're running './run.sh setup', we've paused the script for a few seconds to give you time"
        msg yellow " > to read this message. The easy installer will continue shortly..."
        sleep 10
        return
    fi

    if yesno "${GREEN}Would you like us to automatically setup your PostgreSQL user + database?${RESET} (y/n) > "; then
        local _pg_pass="$(gen_pass)"

        msg cyan "     > Creating PostgreSQL account 'eoshistory' ..."
        /usr/bin/env sudo -i -H -u postgres createuser -SDRl eoshistory
        msg green "     [+] Done."

        msg cyan "     > Setting 'eoshistory' account password to '${_pg_pass}' ..."
        /usr/bin/env sudo -i -H -u postgres psql -c "ALTER USER eoshistory WITH PASSWORD '${_pg_pass}';"
        msg green "     [+] Done."

        msg cyan "     > Saving DB_USER, DB_NAME and DB_PASS to your .env file at '${env_path}' ..."
        echo "DB_USER=eoshistory" >>"$env_path"
        echo "DB_NAME=eoshistory" >>"$env_path"
        echo "DB_PASS=${_pg_pass}" >>"$env_path"
        msg green "     [+] Done."

        msg cyan "     > Creating PostgreSQL database 'eoshistory' owned by 'eoshistory' ..."
        /usr/bin/env sudo -i -H -u postgres createdb -O eoshistory eoshistory
        msg green "     [+] Done."
        msg bold green "\n >>> ### Finished automatically configuring PostgreSQL :) ###\n"

    else
        msg yellow "\n [...] You said *no* to automatic database setup. Skipping automatic database setup.\n"
    fi
}

_debug "??? begin case statement for first param..."
msg
case "$1" in
    queue | celery)
        CELERY_QUEUE="eoshist"
        if (($# > 1)); then
            CELERY_WORKERS=$2
            msg ts bold green "Additional argument detected. If CELERY_WORKERS was set in environment it will"
            msg ts bold green "be ignored - using passed argument '$2' for CELERY_WORKERS instead."
            sleep 1
        fi
        if (($# > 2)); then
            CELERY_QUEUE="$3"
            msg ts bold green "Third argument detected. Using Celery queue $CELERY_QUEUE"
        fi

        if [ -z "$CELERY_WORKERS" ]; then
            msg ts bold green "Starting EOS History Celery Workers (workers: auto / match CPU cores)\n"
            msg ts bold green "NOTE: You can set CELERY_WORKERS in .env to manually set the amount of workers"
            msg ts bold green "\t e.g.   CELERY_WORKERS=20\n"
            sleep 1
            pipenv run celery worker -l INFO -Q "$CELERY_QUEUE" -A eoshistory
        else
            CELERY_WORKERS=$((CELERY_WORKERS))
            msg ts bold green "CELERY_WORKERS was set in environment. Using $CELERY_WORKERS workers instead of auto."
            sleep 1
            msg ts bold green "Starting EOS History Celery Workers (workers: $CELERY_WORKERS)"
            pipenv run celery worker -l INFO -Q "$CELERY_QUEUE" -c "$CELERY_WORKERS" -A eoshistory
        fi
        ;;
    sync* | block* | cron)
        msg ts bold green "Running sync_blocks management command to import blocks"
        pipenv run ./manage.py sync_blocks
        ;;
    show_dep* | print_dep*)
        msg cyan "Below is the status of dependencies you have or don't have installed:\n"
        print_deps
        msg
        msg cyan "You can install all dependencies with '$0 deps'"
        ;;
    dep*)
        install_deps
        ;;
    db_setup | auto_setup_db)
        _debug "??? [case 'db_setup'] starting case for 'db_setup' / 'auto_setup_db'..."
        check_psql
        auto_setup_db
        _debug "??? [case 'db_setup'] end of case for 'db_setup' / 'auto_setup_db'..."
        ;;
    setup | install)
        _debug "??? [case 'setup'] starting case for 'setup' / 'install'..."
        if [[ ! -f "$env_path" ]] || ! grep -q "SECRET_KEY" "$env_path"; then
            msg ts yellow " !!! Either you don't have a .env file, or it's missing a SECRET_KEY... We'll fix that."
            msg ts bold green " >>> Generating a random SECRET_KEY and creating or adding to env file at: $env_path"
            echo "SECRET_KEY=$(gen_pass 64)" >>"$env_path"
        fi

        _debug "??? [case 'setup'] checking HAS_ALLDEPS..."
        if [[ "$HAS_ALLDEPS" != 'y' ]]; then
            msg bold yellow " [!!!] WARNING: It looks like you might be missing some packages required for EOSHistory to run."
            msg
            print_deps
            msg
            if yesno "${CYAN}Do you want us to automatically attempt to install them using 'apt'? (y/n) > "; then
                install_deps
            else
                msg yellow " [---] Okay. We'll attempt to continue with the installation without the required packages.\n"
            fi
            msghr
        else
            check_pipenv
        fi
        msg
        _debug "??? [case 'setup'] calling check_psql..."
        check_psql
        msghr
        _debug "??? [case 'setup'] calling auto_setup_db..."
        auto_setup_db
        msghr

        msg ts bold green " >>> Running 'pipenv install' to install python dependencies + set up virtualenv"
        pipenv install
        msghr

        msg ts bold green " >>> Running database migrations using database connection:${CYAN} $_DB_URL "
        pipenv run ./manage.py migrate
        msghr

        msg ts bold green " >>> Copying static files from Django and plugins into ${_RUN_DIR}/static/ ..."
        pipenv run ./manage.py collectstatic --no-input
        msghr

        msg bold green " >>> Time to create a superuser account. Your superuser account can be used to access "
        msg bold green "     the Django admin panel at /admin/ - if this will be a public facing API, then make "
        msg bold green "     sure you choose a strong password!"
        msg
        pipenv run ./manage.py createsuperuser

        _debug "??? [case 'setup'] end of case 'setup' / 'install'..."
        ;;
    update | upgrade)
        msg ts bold green " >> Updating files from Github"
        git pull
        msg ts bold green " >> Updating Python packages"
        pipenv update
        msg ts bold green " >> Migrating the Postgres database"
        pipenv run ./manage.py migrate
        msg ts bold green " +++ Finished"
        msghr
        echo
        msg ts bold cyan " >> Checking if eoshistory systemd services are installed..."
        if systemctl list-units | grep -q eoshistory; then
            if [ "$EUID" -eq 0 ]; then
                _debug "??? user appears to be root. ."
                msg ts bold green " >>> Restarting eoshistory.service..."
                systemctl restart eoshistory
                msg ts bold green " >>> Restarting eoshistory-celery.service..."
                systemctl restart eoshistory-celery
            elif has_sudo; then
                _debug "??? user is not root. has_sudo was true. restarting with sudo..."
                msg ts bold green " >>> Restarting eoshistory.service..."
                sudo systemctl restart eoshistory
                msg ts bold green " >>> Restarting eoshistory-celery.service..."
                sudo systemctl restart eoshistory-celery
            else
                _debug "??? user is not root. has_sudo was false. cannot auto restart..."
                msg yellow " [!!!] You're not root and you don't have passwordless sudo available."
                msg yellow " [!!!] This means we can't automatically restart the systemd services."
                msg yellow " [!!!] Please remember to restart all EOS History services AS ROOT like so:"
                msg blue "\t\t systemctl restart eoshistory eoshistory-celery"
            fi
        else
            msg yellow " [???] Could not detect any eoshistory systemd units installed"
            msg yellow " [???] If you have any background services set up for running EOSHistory, make sure to"
            msg yellow " [???] restart them for the updates to take effect.\n"
        fi
        msghr

        msg bold yellow "Post-update info:"
        msg yellow "Please **become root**, and read any additional step(s) below to finish your update:\n"
        msg yellow "\t - You may wish to update your systemd service files in-case there are any changes:\n"
        msg blue "\t\t cp -v *.service /etc/systemd/system/"
        msg blue "\t\t # Open the service files with an editor and adjust them for your installation"
        msg blue "\t\t nano /etc/systemd/system/eoshistory.service"
        msg blue "\t\t nano /etc/systemd/system/eoshistory-celery.service"
        msg blue "\t\t # Reload systemd for it to detect the new service files"
        msg blue "\t\t systemctl daemon-reload\n"
        msg yellow "\t - After updating the service files, please remember to restart all EOS History" \
            "services AS ROOT like so:\n"
        msg blue "\t\t systemctl restart eoshistory eoshistory-celery\n"

        msghr
        msg bold green " ### Updater Finished Successfully :) ###"
        msghr

        ;;

    serve* | runserv*)
        # Override these defaults inside of `.env`
        : ${HOST='127.0.0.1'}
        : ${PORT='8287'}
        : ${GU_WORKERS='4'} # Number of Gunicorn worker processes

        pipenv run gunicorn --timeout 600 -b "${HOST}:${PORT}" -w "$GU_WORKERS" eoshistory.wsgi
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

_debug "??? end case statement for first param..."

msg
