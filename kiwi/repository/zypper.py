# Copyright (c) 2015 SUSE Linux GmbH.  All rights reserved.
#
# This file is part of kiwi.
#
# kiwi is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# kiwi is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with kiwi.  If not, see <http://www.gnu.org/licenses/>
#
import os
from six.moves.configparser import ConfigParser
from tempfile import NamedTemporaryFile

# project
from kiwi.command import Command
from kiwi.repository.base import RepositoryBase
from kiwi.path import Path

from kiwi.exceptions import (
    KiwiRepoTypeUnknown
)


class RepositoryZypper(RepositoryBase):
    """
    Implements repo handling for zypper package manager
    """
    def post_init(self, custom_args=None):
        """
        Post initialization method

        Store custom zypper arguments and create runtime configuration
        and environment

        Attributes

        * :attr:`shared_zypper_dir`
            shared directory between image root and build system root

        * :attr:`runtime_zypper_config_file`
            zypper runtime config file name

        * :attr:`runtime_zypp_config_file`
            libzypp runtime config file name

        * :attr:`zypper_args`
            zypper caller args plus additional custom args

        * :attr:`command_env`
            customized os.environ for zypper

        * :attr:`runtime_zypper_config`
            Instance of ConfigParser

        :param list custom_args: zypper arguments
        """
        self.custom_args = custom_args
        self.exclude_docs = False
        self.gpgcheck = False
        if not custom_args:
            self.custom_args = []

        # extract custom arguments used for zypp config only
        if 'exclude_docs' in self.custom_args:
            self.custom_args.remove('exclude_docs')
            self.exclude_docs = True

        if 'check_signatures' in self.custom_args:
            self.custom_args.remove('check_signatures')
            self.gpgcheck = True

        self.repo_names = []

        # zypper support by default point all actions into the root
        # directory of the image system. This information is passed
        # as arguments to zypper and adapted if the call runs as
        # chrooted operation. Therefore the use of the shared location
        # via RootBind::mount_shared_directory is optional but
        # recommended to make use of the repo cache
        manager_base = self.root_dir + self.shared_location

        self.shared_zypper_dir = {
            'pkg-cache-dir': os.sep.join(
                [manager_base, 'packages']
            ),
            'reposd-dir': os.sep.join(
                [manager_base, 'zypper/repos']
            ),
            'credentials-dir': os.sep.join(
                [manager_base, 'zypper/credentials']
            ),
            'solv-cache-dir': os.sep.join(
                [manager_base, 'zypper/solv']
            ),
            'raw-cache-dir': os.sep.join(
                [manager_base, 'zypper/raw']
            ),
            'cache-dir': os.sep.join(
                [manager_base, 'zypper']
            )
        }

        self.runtime_zypper_config_file = NamedTemporaryFile(
            dir=self.root_dir
        )
        self.runtime_zypp_config_file = NamedTemporaryFile(
            dir=self.root_dir
        )

        self.zypper_args = [
            '--non-interactive',
            '--pkg-cache-dir', self.shared_zypper_dir['pkg-cache-dir'],
            '--reposd-dir', self.shared_zypper_dir['reposd-dir'],
            '--solv-cache-dir', self.shared_zypper_dir['solv-cache-dir'],
            '--cache-dir', self.shared_zypper_dir['cache-dir'],
            '--raw-cache-dir', self.shared_zypper_dir['raw-cache-dir'],
            '--config', self.runtime_zypper_config_file.name
        ] + self.custom_args

        self.command_env = self._create_zypper_runtime_environment()

        # config file parameters for zypper tool
        self.runtime_zypper_config = ConfigParser()
        self.runtime_zypper_config.add_section('main')

        # config file parameters for libzypp library
        self.runtime_zypp_config = ConfigParser()
        self.runtime_zypp_config.add_section('main')
        self.runtime_zypp_config.set(
            'main', 'credentials.global.dir',
            self.shared_zypper_dir['credentials-dir']
        )
        if self.exclude_docs:
            self.runtime_zypp_config.set(
                'main', 'rpm.install.excludedocs', 'yes'
            )

        if self.gpgcheck:
            self.runtime_zypp_config.set(
                'main', 'pkg_gpgcheck', '1'
            )
            self.runtime_zypp_config.set(
                'main', 'repo_gpgcheck', '1'
            )
        else:
            self.runtime_zypp_config.set(
                'main', 'gpgcheck', '0'
            )

        self._write_runtime_config()

    def use_default_location(self):
        """
        Setup zypper repository operations to store all data
        in the default places
        """
        self.shared_zypper_dir['reposd-dir'] = \
            self.root_dir + '/etc/zypp/repos.d'
        self.shared_zypper_dir['credentials-dir'] = \
            self.root_dir + '/etc/zypp/credentials.d'
        self.zypper_args = [
            '--non-interactive',
        ] + self.custom_args
        self.command_env = dict(os.environ, LANG='C')

    def runtime_config(self):
        """
        zypper runtime configuration and environment
        """
        return {
            'zypper_args': self.zypper_args,
            'command_env': self.command_env
        }

    def add_repo(
        self, name, uri, repo_type='rpm-md',
        prio=None, dist=None, components=None,
        user=None, secret=None, credentials_file=None
    ):
        """
        Add zypper repository

        :param string name: repository name
        :param string uri: repository URI
        :param repo_type: repostory type name
        :param int prio: zypper repostory priority
        :param dist: unused
        :param components: unused
        :param user: credentials username
        :param secret: credentials password
        :param credentials_file: zypper credentials file
        """
        if credentials_file:
            repo_secret = os.sep.join(
                [self.shared_zypper_dir['credentials-dir'], credentials_file]
            )
            if os.path.exists(repo_secret):
                Path.wipe(repo_secret)

            if user and secret:
                uri = ''.join([uri, '?credentials=', credentials_file])
                with open(repo_secret, 'w') as credentials:
                    credentials.write('username={0}'.format(user))
                    credentials.write('password={0}'.format(secret))

        repo_file = ''.join(
            [self.shared_zypper_dir['reposd-dir'], '/', name, '.repo']
        )
        self.repo_names.append(''.join([name, '.repo']))

        if os.path.exists(repo_file):
            Path.wipe(repo_file)

        self._backup_package_cache()
        Command.run(
            ['zypper'] + self.zypper_args + [
                '--root', self.root_dir,
                'addrepo',
                '--refresh',
                '--type', self._translate_repo_type(repo_type),
                '--keep-packages',
                '-C',
                uri,
                name
            ],
            self.command_env
        )
        if prio:
            Command.run(
                ['zypper'] + self.zypper_args + [
                    '--root', self.root_dir,
                    'modifyrepo', '--priority', format(prio), name
                ],
                self.command_env
            )
        self._restore_package_cache()

    def delete_repo(self, name):
        """
        Delete zypper repository

        :param string name: repository name
        """
        Command.run(
            ['zypper'] + self.zypper_args + [
                '--root', self.root_dir, 'removerepo', name
            ],
            self.command_env
        )

    def delete_all_repos(self):
        """
        Delete all zypper repositories
        """
        Path.wipe(self.shared_zypper_dir['reposd-dir'])
        Path.create(self.shared_zypper_dir['reposd-dir'])

    def delete_repo_cache(self, name):
        """
        Delete zypper repository cache

        The cache data for each repository is stored in a directory
        of the same name as the repository name. The method deletes
        this directory to cleanup the cache information

        :param string name: repository name
        """
        Path.wipe(
            os.sep.join([self.shared_zypper_dir['pkg-cache-dir'], name])
        )

    def cleanup_unused_repos(self):
        """
        Delete unused zypper repositories

        zypper creates a system solvable which is unwanted for the
        purpose of building images. In addition zypper fails with
        an error message 'Failed to cache rpm database' if such a
        system solvable exists and a new root system is created

        All other repository configurations which are not used for
        this build must be removed too, otherwise they are taken into
        account for the package installations
        """
        solv_dir = self.shared_zypper_dir['solv-cache-dir']
        Path.wipe(solv_dir + '/@System')

        repos_dir = self.shared_zypper_dir['reposd-dir']
        repo_files = list(os.walk(repos_dir))[0][2]
        for repo_file in repo_files:
            if repo_file not in self.repo_names:
                Path.wipe(repos_dir + '/' + repo_file)

    def _create_zypper_runtime_environment(self):
        for zypper_dir in list(self.shared_zypper_dir.values()):
            Path.create(zypper_dir)
        return dict(
            os.environ,
            LANG='C',
            ZYPP_CONF=self.runtime_zypp_config_file.name
        )

    def _write_runtime_config(self):
        with open(self.runtime_zypper_config_file.name, 'w') as config:
            self.runtime_zypper_config.write(config)
        with open(self.runtime_zypp_config_file.name, 'w') as config:
            self.runtime_zypp_config.write(config)

    def _translate_repo_type(self, repo_type):
        """
            Translate kiwi supported common repo type names from the schema
            into the name the zyper package manager understands
        """
        zypper_type_for = {
            'rpm-md': 'YUM',
            'rpm-dir': 'Plaindir',
            'yast2': 'YaST'
        }
        try:
            return zypper_type_for[repo_type]
        except Exception:
            raise KiwiRepoTypeUnknown(
                'Unsupported zypper repo type: %s' % repo_type
            )

    def _backup_package_cache(self):
        """
        preserve package cache which otherwise will be removed by
        zypper if no repo file is found. But this situation is
        normal for an image build process which setup and remove
        repos for building at runtime
        """
        self._move_package_cache(backup=True)

    def _restore_package_cache(self):
        """
        restore preserved package cache at the location passed to zypper
        """
        self._move_package_cache(restore=True)

    def _move_package_cache(self, backup=False, restore=False):
        package_cache = self.shared_location + '/packages'
        package_cache_moved = package_cache + '.moved'
        if backup and os.path.exists(package_cache):
            Command.run(
                ['mv', '-f', package_cache, package_cache_moved]
            )
        elif restore and os.path.exists(package_cache_moved):
            Command.run(
                ['mv', '-f', package_cache_moved, package_cache]
            )

    def __del__(self):
        self._restore_package_cache()
