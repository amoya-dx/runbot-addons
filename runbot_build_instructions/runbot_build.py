# -*- encoding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    This module copyright (C) 2010 - 2014 Savoir-faire Linux
#    (<http://www.savoirfairelinux.com>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import logging
import os
import sys
import shutil

import openerp
from openerp.osv import orm, fields
from openerp.addons.runbot.runbot import mkdirs

_logger = logging.getLogger(__name__)


def custom_build(func):
    """Decorator for functions which should be overwritten only if
    is_custom_build is enabled in repo.
    """
    def custom_func(self, cr, uid, ids, context=None):
        args = [
            ('id', 'in', ids),
            ('branch_id.repo_id.is_custom_build', '=', True)
        ]
        custom_ids = self.search(cr, uid, args, context=context)
        regular_ids = list(set(ids) - set(custom_ids))
        ret = None
        if regular_ids:
            regular_func = getattr(super(runbot_build, self), func.func_name)
            ret = regular_func(cr, uid, regular_ids, context=context)
        if custom_ids:
            assert ret is None
            ret = func(self, cr, uid, custom_ids, context=context)
        return ret
    return custom_func


class runbot_build(orm.Model):
    _inherit = "runbot.build"
    _columns = {
        'prebuilt': fields.boolean("Prebuilt"),
    }

    def job_00_prebuild(self, cr, uid, build, lock_path, log_path):
        build._log('test_base', 'Start pre-build commands')
        # checkout source
        build.checkout()
        if build.branch_id.repo_id.is_custom_build:
            build.pre_build(lock_path, log_path)
        build.prebuilt = True

    def sub_cmd(self, build, cmd):
        if not cmd:
            return []
        if isinstance(cmd, basestring):
            cmd = cmd.split()
        internal_vals = {
            'custom_build_dir': build.repo_id.custom_build_dir or '',
            'custom_server_path': build.repo_id.custom_server_path,
        }
        return [i % internal_vals for i in cmd]

    def pre_build(self, cr, uid, ids, lock_path, log_path, context=None):
        """Run pre-build command if there is one
        Substitute path variables after splitting command to avoid problems
        with spaces in internal variables.
        Run command in build path to avoid relative path issues.
        """
        pushd = os.getcwd()
        try:
            for build in self.browse(cr, uid, ids, context=context):
                if build.prebuilt:
                    continue
                cmd = self.sub_cmd(build, build.repo_id.custom_pre_build_cmd)
                if not cmd:
                    continue
                os.chdir(build.path())
                self.spawn(cmd, lock_path, log_path)

        finally:
            os.chdir(pushd)

    @custom_build
    def checkout(self, cr, uid, ids, context=None):
        """Checkout in custom build directories if they are specified
        Do same as superclass except for git_export path.
        """
        for build in self.browse(cr, uid, ids, context=context):
            if build.prebuilt:
                continue
            # starts from scratch
            if os.path.isdir(build.path()):
                shutil.rmtree(build.path())

            # runbot log path
            mkdirs([build.path("logs")])

            # checkout branch
            build_path = build.path()
            custom_build_dir = build.repo_id.custom_build_dir
            if custom_build_dir:
                mkdirs([build.path(custom_build_dir)])
                build_path = os.path.join(build_path, custom_build_dir)
            build.repo_id.git_export(build.name, build_path)

    @custom_build
    def cmd(self, cr, uid, ids, context=None):
        """Get server start script from build config
        Overwrite superclass completely
        Specify database user in the case of custom config, to allow viewing
        after db has been created by Odoo (using current user).
        Disable multiworker
        """
        build = self.browse(cr, uid, ids[0], context=context)
        server_path = build.path(build.repo_id.custom_server_path)
        mods = build.repo_id.modules or "base"
        params = self.sub_cmd(build, build.repo_id.custom_server_params)
        # commandline
        cmd = [
            sys.executable,
            server_path,
            "--no-xmlrpcs",
            "--xmlrpc-port=%d" % build.port,
            "--db_user=%s" % openerp.tools.config['db_user'],
            "--workers=0",
        ] + params
        return cmd, mods
