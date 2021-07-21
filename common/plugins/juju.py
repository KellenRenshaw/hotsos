import os

import re

from common import (
    constants,
    plugintools,
)
from common.cli_helpers import CLIHelper

JUJU_LOG_PATH = os.path.join(constants.DATA_ROOT, "var/log/juju")
JUJU_LIB_PATH = os.path.join(constants.DATA_ROOT, "var/lib/juju")
CHARM_MANIFEST_GLOB = "agents/unit-*/state/deployer/manifests"


class JujuChecksBase(plugintools.PluginPartBase):

    def _get_app_from_unit_name(self, unit):
        ret = re.compile(r"([0-9a-z\-]+)-[0-9]+.*").match(unit)
        if ret:
            return ret[1]

    def _get_unit_version(self, unit):
        ret = re.compile(r"[0-9a-z\-]+-([0-9]+).*").match(unit)
        if ret:
            return int(ret[1])

    def _get_ps_units(self):
        units = set()
        for line in CLIHelper().ps():
            if "unit-" in line:
                ret = re.compile(r".+unit-([0-9a-z\-]+-[0-9]+).*").match(line)
                if ret:
                    units.add(ret[1])

        return units

    def _get_log_units(self):
        units = set()
        for logfile in os.listdir(JUJU_LOG_PATH):
            ret = re.compile(r"unit-(.+)\.log$").match(logfile)
            if ret:
                units.add(ret[1])

        return units

    def _get_local_running_units(self):
        units = self.get_ps_units()
        return units.intersection(self.get_log_units())
