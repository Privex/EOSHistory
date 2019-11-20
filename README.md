# Privex EOS History API

Our **EOS History API** is a Django application which uses Celery for high speed, asynchronous
block / transaction importing.

 

# Installation

Quickstart (Tested on Ubuntu Bionic 18.04 - may work on other Debian-based distros):

**Install dependencies and the project**

```
# Install dependencies
sudo apt update -y
sudo apt install -y git python3.7 python3.7-venv python3.7-dev redis-server libpq-dev

# If you don't have the Postgres database server installed, then you should install it
# (you can also set it up on another host if you know what you're doing)
apt install -y postgresql

# Install rabbitmq-server
sudo apt -y install rabbitmq-server

# Install pip3
sudo apt install python3-pip
 
# Install pipenv if you don't already have it
sudo pip3 install pipenv

# Clone the repo
git clone https://github.com/Privex/EOSHistory.git
cd EOSHistory

# Create a virtualenv + install required Python packages
pipenv install

```

**Set up database**

To protect against timezone issues, set your PostgreSQL timezone to UTC in `postgresql.conf` located in /etc/postgresql/<version>/main/.

```
timezone = 'UTC'
```


To create a database and db user, you may need to log in as the `postgres` user.

```
# Log in as the postgres user
root@host # su - postgres

# Create a user, you'll be prompted for the password
# S = not a superuser, D = cannot create databases, R = cannot create roles
# l = can login, P = prompt for user's new password
$ createuser -SDRl -P eoshistory
    Enter password for new role:
    Enter it again:

# Create the database with the new user as the owner

$ createdb -O eoshistory eoshistory

# If you've already created the DB, use psql to manually grant permissions to the user

$ psql
    psql (10.6 (Ubuntu 10.6-0ubuntu0.18.04.1))
    Type "help" for help.

    postgres=# GRANT ALL ON DATABASE eoshistory TO eoshistory;

```

**Configure your .env file in ~/EOSHistory**

```
# Name of the PostgreSQL database
DB_NAME=eoshistory
DB_USER=eoshistory
DB_PASS=MySecurePostgresPass **** <--- Replace with the password created above ****

# Default is relative - meaning EOS_START_BLOCK becomes "start from this many blocks behind head"
# You can change this to 'exact', which changes EOS_START_BLOCK to be "start from this exact block number"
EOS_START_TYPE=relative

# This is the default RPC node and is shown just to let you know you can change it :)
EOS_NODE=https://eos.greymass.com

# Default is 1,210,000 blocks = 605,000 seconds = approx. 7 days of blocks.
# This means on a blank database, it will begin syncing EOS blocks to the database starting at 1,210,000 blocks ago.
EOS_START_BLOCK=1210000

# Maximum amount of blocks to queue for import in the background, after which sync_blocks
# will wait for the queued blocks to finish importing before it continues.
EOS_SYNC_MAX_QUEUE=500
```

**Run migrations and create an Admin user**

```sh
cd ~/EOSHistory
pipenv shell
# Run database migrations
./manage.py migrate
# Create admin account for login
./manage.py createsuperuser
```

**Run the EOS History API server**

```sh
# In development, you can use runserver
./manage.py runserver

# In production, you should use gunicorn instead
./run.sh serve

# Alternatively you can run gunicorn manually:
gunicorn -b '127.0.0.1:8287' eoshistory.wsgi
```

**Start the celery worker and run the block importer command**

```sh
# Easy way - using run.sh queue
./run.sh queue
# Alternatively: run celery manually
# You can add '-c 8' for example to manually set how many celery workers to run
# Otherwise it will run as many workers as you have CPU cores 
pipenv run celery worker -A eoshistory

# Begin syncing EOSHistory with the EOS blockchain
# This runs the sync_blocks management command, which fires import block tasks into the background
# for celery to process
./run.sh sync

```

**Production notes**

You should copy ``eoshistory.service`` and ``eoshistory-celery.service`` into `/etc/systemd/system/`,
adjust the username / paths, and then enable + start the services to run both the API server (gunicorn) and
the Celery workers in the background, with automatic restart and starting on boot.

```sh
cp *.service /etc/systemd/system/
# Adjust the usernames / paths as needed
nano /etc/systemd/system/eoshistory.service
nano /etc/systemd/system/eoshistory-celery.service
# Enable and start the services
systemctl enable eoshistory eoshistory-celery
systemctl restart eoshistory eoshistory-celery
```

You should also set up a cron to run `sync_blocks` regularly, e.g. once per minute.

You don't have to worry about the cron running more than once, as it uses
[Privex's Django Lock Manager](https://github.com/Privex/django-lockmgr) to ensure
only one instance of the block syncing command is running at any given time.


```sh
$ crontab -e

# m    h  dom mon dow   command
  *    *   *   *   *    /home/lg/EOSHistory/run.sh cron
```

# Improving performance in production

The initial sync of block history can take some time, but there's many factors that can affect the sync speed,
including congestion of the EOS RPC node, the cache backend you're using, your hardware, or special tuning
settings such as `EOS_SYNC_MAX_QUEUE`.

You can try some of the tuning tips below if you're unhappy with the sync speed.

### Increase / Decrease the amount of Celery workers

By default, celery (`./run.sh queue` or `./run.sh celery`) will launch as many worker threads as you have CPU cores.

Depending on your CPU, this could either be too many, or too few workers.

There are two ways you can override this (when using run.sh).

1. **Pass the number of workers on the command line** - `./run.sh queue 5` would run 5 workers

2. **Set CELERY_WORKERS in .env** - `CELERY_WORKERS=10` would run 10 workers whenever `./run.sh queue` is ran

Note: CLI arguments take priority. If you set `CELERY_WORKERS` in your `.env` file, then the `.env` value would be
ignored if an amount of workers was passed on the command line e.g. `./run.sh queue 6`

### Adjust `EOS_SYNC_MAX_QUEUE`

By default, `EOS_SYNC_MAX_QUEUE` is set to `500` - which means that **sync_blocks** 
(`./run.sh sync_blocks / blocks / cron`) will queue up 500 blocks for Celery to import in the background, before
it loops through the Celery queue and verifies each block was successfully imported.

Depending on the speed of your system, and how many Celery workers you're running, you may need to play with this
number to find out what gives the best performance when syncing blocks.

### Try different cache backends

By default, EOSHistory will use `django.core.cache.backends.locmem.LocMemCache` (cache inside python app's memory)
if the app is in development mode (i.e. `DEBUG=true` in your .env file).

In production (default, or `DEBUG=false`), EOSHistory uses the cache backend `redis_cache.RedisCache` - which
as the name implies, is a backend to cache using Redis instead.

This cache is used by both the Django application itself, as well as Celery (which handles the background workers
which process blocks).

In some cases, using memcached may be faster than Redis, especially with a load balancing setup.

To switch to memcached, follow the steps below:

First, install memcached and the development headers (required for the python library):

```sh
apt install memcached libmemcached11 libmemcached-dev
```

Next, install the python `pylibmc` library inside of the EOSHistory virtualenv:

```sh
# Enter whatever folder it's installed at
cd ~/EOSHistory
# Install the library into the virtualenv
pipenv run pip3 install pylibmc
```

Now, set / change the cache backend in your `.env` file:

```
CACHE_BACKEND=django.core.cache.backends.memcached.PyLibMCCache
```

If you're running memcached on a different server, you can specify it using `CACHE_LOCATION`.

You can also specify multiple memcached servers for load balancing:

```.env
# Specifying an individual memcached server
CACHE_LOCATION=10.1.2.3:11211
# Specifying multiple memcached servers for load balancing
CACHE_LOCATION=10.1.2.3:11211,10.2.3.5:11211,10.8.9.2:11211
```

Finally, once you've finished installing / configuring it as needed, you should restart the services

```sh
systemctl restart eoshistory eoshistory-celery
```


### 
# License

This project is licensed under the **GNU AGPL v3**

For full details, please see `LICENSE.txt` and `AGPL-3.0.txt`.

Here's the important parts:

 - If you use this software (or substantial parts of it) to run a public service (including any separate user interfaces 
   which use it's API), **you must display a link to this software's source code wherever it is used**.
   
   Example: **This website uses the open source [Privex EOS History](https://github.com/Privex/EOSHistory)
   created by [Privex Inc.](https://www.privex.io)**
   
 - If you modify this software (or substantial portions of it) and make it available to the public in some 
   form (whether it's just the source code, running it as a public service, or part of one) 
    - The modified software (or portion) must remain under the GNU AGPL v3, i.e. same rules apply, public services must
      display a link back to the modified source code.
    - You must attribute us as the original authors, with a link back to the original source code
    - You must keep our copyright notice intact in the LICENSE.txt file

 - Some people interpret the GNU AGPL v3 "linking" rules to mean that you must release any application that interacts
   with our project under the GNU AGPL v3.
   
   To clarify our stance on those rules: 
   
   - If you have a completely separate application which simply sends API requests to a copy of Privex EOS History API
     that you run, you do not have to release your application under the GNU AGPL v3. 
   - However, you ARE required to place a notice on your application, informing your users that your application
     uses Privex EOS History, with a clear link to the source code (see our example at the top)
   - If your application's source code **is inside of Privex EOS History**, i.e. you've added your own Python
     views, templates etc. to a copy of this project, then your application is considered a modification of this
     software, and thus you DO have to release your source code under the GNU AGPL v3.

 - There is no warranty. We're not responsible if you, or others incur any damages from using this software.
 
 - If you can't / don't want to comply with these license requirements, or are unsure about how it may affect
   your particular usage of the software, please [contact us](https://www.privex.io/contact/). 
   We may offer alternative licensing for parts of, or all of this software at our discretion.



# Contributing

We're very happy to accept pull requests, and work on any issues reported to us. 

Here's some important information:

**Reporting Issues:**

 - For bug reports, you should include the following information:
     - Version of the project you're using - `git log -n1`
     - The Python package versions you have installed - `pip3 freeze`
     - Your python3 version - `python3 -V`
     - Your operating system and OS version (e.g. Ubuntu 18.04, Debian 7)
 - For feature requests / changes
     - Clearly explain the feature/change that you would like to be added
     - Explain why the feature/change would be useful to us, or other users of the tool
     - Be aware that features/changes that are complicated to add, or we simply find un-necessary for our use of the tool 
       may not be added (but we may accept PRs)
    
**Pull Requests:**

 - We'll happily accept PRs that only add code comments or README changes
 - Use 4 spaces, not tabs when contributing to the code
 - You can use features from Python 3.4+ (we run Python 3.7+ for our projects)
    - Features that require a Python version that has not yet been released for the latest stable release
      of Ubuntu Server LTS (at this time, Ubuntu 18.04 Bionic) will not be accepted. 
 - Clearly explain the purpose of your pull request in the title and description
     - What changes have you made?
     - Why have you made these changes?
 - Please make sure that code contributions are appropriately commented - we won't accept changes that involve 
   uncommented, highly terse one-liners.

**Legal Disclaimer for Contributions**

Nobody wants to read a long document filled with legal text, so we've summed up the important parts here.

If you contribute content that you've created/own to projects that are created/owned by Privex, such as code or 
documentation, then you might automatically grant us unrestricted usage of your content, regardless of the open source 
license that applies to our project.

If you don't want to grant us unlimited usage of your content, you should make sure to place your content
in a separate file, making sure that the license of your content is clearly displayed at the start of the file 
(e.g. code comments), or inside of it's containing folder (e.g. a file named LICENSE). 

You should let us know in your pull request or issue that you've included files which are licensed
separately, so that we can make sure there's no license conflicts that might stop us being able
to accept your contribution.

If you'd rather read the whole legal text, it should be included as `privex_contribution_agreement.txt`.

# Thanks for reading!

**If this project has helped you, consider [grabbing a VPS or Dedicated Server from Privex](https://www.privex.io) -**
**prices start at as little as US$8/mo (we take cryptocurrency!)**
