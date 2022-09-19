# jenkins-jobcfg

Configure jenkins jobs by editing human friendly yaml description files

## Usage:

### fetch all job configurations

    $ jenkins-jobcfg.py fetch all
    config-example-git-trigger.yaml # only one job avalaible here

### modify and push a job configuration

    # edit a job configuration file
    $ emacs config-example-git-trigger.yaml

    # push the new configuration to jenkins server
    $ jenkins-jobcfg.py push config-example-git-trigger.yaml

    # you can still edit the configuration using the web interface
    # and get the modified config file back
    $ jenkins-jobcfg.py fetch example-git-trigger
    config-example-git-trigger.yaml

### create/duplicate a job

    $ cp config-example-git-trigger.yaml config-example-git-trigger-new.yaml
    # eventually modify config-example-git-trigger-new.yaml
    $ jenkins-jobcfg.py create config-example-git-trigger-new.yaml
    config-example-git-trigger-new.yaml

### delete a job

    $ ./jenkins-jobcfg.py delete example-git-trigger-new
    example-git-trigger-new deleted

## Requirements:

Requires python 3.x and some python modules, for instance on deb systems:

    $ sudo apt-get install python3 python3-pip
    $ pip3 install requests PyYAML xmlplain
