# Copyright 2021 Edward Hope-Morley
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import os

from common import (
    constants,
    plugintools,
)
from common.issue_types import SysCtlWarning
from common.issues_utils import add_issue
from common.cli_helpers import CLIHelper

YAML_PRIORITY = 1


class SystemChecks(plugintools.PluginPartBase):

    def _sysctl_conf(self, path):
        sysctl_key_values = {}
        if not os.path.isfile(path):
            return sysctl_key_values

        with open(path) as fd:
            for line in fd.readlines():
                if line.startswith("#"):
                    continue

                split = line.partition("=")
                if not split[1]:
                    continue

                key = split[0].strip()
                value = split[2].strip()

                # ignore wildcarded keys'
                if '*' in key:
                    continue

                # ignore unsetters
                if key.startswith('-'):
                    continue

                sysctl_key_values[key] = value

        return sysctl_key_values

    def _get_charm_sysctl_d(self):
        """ Collect all key/value pairs defined under /etc/sysctl.d that were
        written by a charm.
        """
        confs = ['50-ceph-osd-charm.conf',
                 '50-nova-compute.conf',
                 '50-openvswitch.conf',
                 '50-swift-storage-charm.conf',
                 '50-quantum-gateway.conf']
        sysctl_key_priorities = {}
        sysctl_key_values = {}
        path = os.path.join(constants.DATA_ROOT, 'etc/sysctl.d')
        if not os.path.isdir(path):
            return

        for conf in confs:
            parsed = self._sysctl_conf(os.path.join(path, conf))
            for key, value in parsed.items():
                if key in sysctl_key_priorities:
                    if sysctl_key_priorities[key] >= conf:
                        continue

                sysctl_key_priorities[key] = conf
                sysctl_key_values[key] = {"value": value, "conf": conf}

        return sysctl_key_values

    def _get_sysctl_d(self):
        """ Collect all key/value pairs defined under /etc/sysctl.d and keep
        the highest priority value for any given key.

        man sysctld specifies that the following locations are searched for
        config so we will include these:

            * /etc/sysctl.d/
            * /usr/lib/sysctl.d/
            * /run/sysctl.d/*.conf
        """
        sysctl_key_priorities = {}
        sysctl_key_values = {}
        for location in ['etc/sysctl.d', 'usr/lib/sysctl.d',
                         'run/sysctl.d']:
            path = os.path.join(constants.DATA_ROOT, location)
            if not os.path.isdir(path):
                continue

            for conf in os.listdir(path):
                parsed = self._sysctl_conf(os.path.join(path, conf))
                for key, value in parsed.items():
                    if key in sysctl_key_priorities:
                        if sysctl_key_priorities[key] >= conf:
                            continue

                    sysctl_key_priorities[key] = conf
                    sysctl_key_values[key] = value

        return sysctl_key_values

    def sysctl_checks(self):
        """ Compare the values for any key set under /etc/sysctl.d and report
        an issue if any mismatches detected.
        """
        sysctls = CLIHelper().sysctl_all()
        actuals = {}
        for kv in sysctls:
            k = kv.partition("=")[0].strip()
            v = kv.partition("=")[2].strip()
            # normalise multi-whitespace into a single
            actuals[k] = ' '.join(v.split())

        mismatch = {}
        sysctld = self._get_sysctl_d()
        for key, value in sysctld.items():
            # some keys will not be readable e.g. when inside an unprivileged
            # container so we just ignore them.
            if value != actuals.get(key, value):
                mismatch[key] = {"actual": actuals[key],
                                 "expected": value}

        charm_mismatch = {}
        charm_sysctld = self._get_charm_sysctl_d()
        for key, info in charm_sysctld.items():
            value = info["value"]
            if value != actuals[key]:
                charm_mismatch[key] = {"conf": info["conf"],
                                       "actual": actuals[key],
                                       "expected": value}

        if mismatch:
            self._output['sysctl-mismatch'] = mismatch
            add_issue(SysCtlWarning("host sysctl not consistent with contents "
                                    "of systcl.d"))

        if charm_mismatch:
            # We dont raise an issue for this sine it is just informational
            self._output['juju-charm-sysctl-mismatch'] = charm_mismatch

    def __call__(self):
        self.sysctl_checks()
