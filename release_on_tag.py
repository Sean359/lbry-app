import argparse
import glob
import json
import logging
import os
import platform
import re
import subprocess
import sys
import zipfile

import github
import requests
import uritemplate

from lbrynet.core import log_support


def main(args=None):
    gh_token = os.environ['GH_TOKEN']
    auth = github.Github(gh_token)
    app_repo = auth.get_repo('lbryio/lbry-app')
    # TODO: switch lbryio/lbrynet-daemon to lbryio/lbry
    daemon_repo = auth.get_repo('lbryio/lbrynet-daemon')

    artifact = get_artifact()

    current_tag = None
    try:
        current_tag = subprocess.check_output(
            ['git', 'describe', '--exact-match', 'HEAD']).strip()
    except subprocess.CalledProcessError:
        log.info('Stopping as we are not currently on a tag')
        return
    if not check_repo_has_tag(app_repo, current_tag):
        log.info('Tag %s is not in repo %s', current_tag, app_repo)
        # TODO: maybe this should be an error
        return

    release = get_release(app_repo, current_tag)
    upload_asset(release, artifact, gh_token)

    release = get_release(daemon_repo, current_tag)
    artifact = os.path.join('app', 'dist', 'lbrynet-daemon')
    if platform.system() == 'Windows':
        artifact += '.exe'
    asset_to_upload = get_asset(artifact, get_system_label())
    upload_asset(release, asset_to_upload, gh_token)


def check_repo_has_tag(repo, target_tag):
    tags = repo.get_tags().get_page(0)
    for tag in tags:
        if tag.name == target_tag:
            return True
    return False


def get_release(current_repo, current_tag):
    return current_repo.get_release(current_tag)


def get_artifact():
    system = platform.system()
    if system == 'Darwin':
        return glob.glob('dist/mac/LBRY*.dmg')[0]
    elif system == 'Linux':
        return glob.glob('dist/LBRY*.deb')[0]
    elif system == 'Windows':
        return glob.glob('dist/LBRY*.exe')[0]
    else:
        raise Exception("I don't know about any artifact on {}".format(system))


def get_system_label():
    system = platform.system()
    if system == 'Darwin':
        return 'macOS'
    else:
        return system


def get_asset(filename, label):
    label = '-{}'.format(label)
    base, ext = os.path.splitext(filename)
    # TODO: probably want to clean this up
    zipfilename = '{}{}.zip'.format(base, label)
    with zipfile.ZipFile(zipfilename, 'w') as myzip:
        myzip.write(filename)
    return zipfilename


def upload_asset(release, asset_to_upload, token):
    basename = os.path.basename(asset_to_upload)
    if is_asset_already_uploaded(release, basename):
        return
    upload_uri = uritemplate.expand(
        release.upload_url, {'name': basename})
    # using requests.post fails miserably with SSL EPIPE errors. I spent
    # half a day trying to debug before deciding to switch to curl.
    cmd = [
        'curl', '-sS', '-X', 'POST', '-u', ':{}'.format(os.environ['GH_TOKEN']),
        '--header', 'Content-Type:application/zip',
        '--data-binary', '@{}'.format(asset_to_upload), upload_uri
    ]
    raw_output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    output = json.loads(raw_output)
    if 'errors' in output:
        raise Exception(output)
    else:
        log.info('Successfully uploaded to %s', output['browser_download_url'])


def is_asset_already_uploaded(release, basename):
    for asset in release.raw_data['assets']:
        if asset['name'] == basename:
            log.info('File %s has already been uploaded to %s', basename, release.tag_name)
            return True
    return False


if __name__ == '__main__':
    log = logging.getLogger('release-on-tag')
    log_support.configure_console(level='DEBUG')
    sys.exit(main())
else:
    log = logging.getLogger(__name__)