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

import re
import os

from common import constants
from common.cli_helpers import CmdBase
from common.plugins.openstack import (
    OST_PROJECTS,
    OST_SERVICES_DEPS,
    OST_SERVICES_EXPRS,
    OpenstackConfig,
    OpenstackServiceChecksBase,
)

# configs that dont use standard /etc/<project>/<project>.conf
OST_ETC_OVERRIDES = {"glance": "glance-api.conf",
                     "swift": "proxy.conf"}

APT_SOURCE_PATH = os.path.join(constants.DATA_ROOT, "etc/apt/sources.list.d")
YAML_PRIORITY = 0


class OpenstackServiceChecks(OpenstackServiceChecksBase):

    def __init__(self):
        service_exprs = OST_SERVICES_EXPRS + OST_SERVICES_DEPS
        super().__init__(service_exprs=service_exprs, hint_range=(0, 3))

    def get_running_services_info(self):
        """Get string info for running services."""
        if self.services:
            self._output["services"] = self.get_service_info_str()

    def get_release_info(self):
        if not os.path.exists(APT_SOURCE_PATH):
            return

        release_info = {}
        for source in os.listdir(APT_SOURCE_PATH):
            apt_path = os.path.join(APT_SOURCE_PATH, source)
            for line in CmdBase.safe_readlines(apt_path):
                rexpr = r"deb .+ubuntu-cloud.+ [a-z]+-([a-z]+)/([a-z]+) .+"
                ret = re.compile(rexpr).match(line)
                if ret:
                    if "uca" not in release_info:
                        release_info["uca"] = set()

                    if ret[1] != "updates":
                        release_info["uca"].add("{}-{}".format(ret[2], ret[1]))
                    else:
                        release_info["uca"].add(ret[2])

        if release_info:
            if release_info.get("uca"):
                self._output["release"] = sorted(release_info["uca"],
                                                 reverse=True)[0]
        else:
            self._output["release"] = "distro"

    def get_debug_log_info(self):
        debug_enabled = {}
        for proj in OST_PROJECTS:
            conf = OST_ETC_OVERRIDES.get(proj)
            if conf is None:
                conf = "{}.conf".format(proj)

            path = os.path.join(constants.DATA_ROOT, "etc", proj, conf)
            cfg = OpenstackConfig(path)
            if cfg.exists:
                debug_enabled[proj] = cfg.get("debug", section="DEFAULT")

        if debug_enabled:
            self._output["debug-logging-enabled"] = debug_enabled

    def __call__(self):
        self.get_release_info()
        self.get_running_services_info()
        self.get_debug_log_info()
