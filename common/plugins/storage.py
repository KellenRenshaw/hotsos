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

import glob
import os
import re

from common import (
    checks,
    constants,
    host_helpers,
    plugintools,
    utils,
)
from common.cli_helpers import CLIHelper
from common.searchtools import (
    FileSearcher,
    SequenceSearchDef,
    SearchDef
)


CEPH_SERVICES_EXPRS = [r"ceph-[a-z0-9-]+",
                       r"rados[a-z0-9-:]+"]
CEPH_PKGS_CORE = [r"ceph-[a-z-]+",
                  r"rados[a-z-]+",
                  r"rbd",
                  ]
CEPH_LOGS = "var/log/ceph/"


class StorageBase(plugintools.PluginPartBase):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class CephConfig(checks.SectionalConfigBase):
    def __init__(self, *args, **kwargs):
        path = os.path.join(constants.DATA_ROOT, 'etc/ceph/ceph.conf')
        super().__init__(path=path, *args, **kwargs)


class CephBase(StorageBase):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ceph_config = CephConfig()
        self._bcache_info = []
        udevadm_db = CLIHelper().udevadm_info_exportdb()
        if udevadm_db:
            self.udevadm_db = utils.mktemp_dump('\n'.join(udevadm_db))
        else:
            self.udevadm_db = None

    def __del__(self):
        if self.udevadm_db:
            os.unlink(self.udevadm_db)

    @property
    def bind_interfaces(self):
        """
        If ceph is using specific network interfaces, return them as a dict.
        """
        pub_net = self.ceph_config.get('public network')
        pub_addr = self.ceph_config.get('public addr')
        clus_net = self.ceph_config.get('cluster network')
        clus_addr = self.ceph_config.get('cluster addr')

        interfaces = {}
        if not any([pub_net, pub_addr, clus_net, clus_addr]):
            return interfaces

        nethelp = host_helpers.HostNetworkingHelper()

        if pub_net:
            iface = nethelp.get_interface_with_addr(pub_net).to_dict()
            interfaces.update(iface)
        elif pub_addr:
            iface = nethelp.get_interface_with_addr(pub_addr).to_dict()
            interfaces.update(iface)

        if clus_net:
            iface = nethelp.get_interface_with_addr(clus_net).to_dict()
            interfaces.update(iface)
        elif clus_addr:
            iface = nethelp.get_interface_with_addr(clus_addr).to_dict()
            interfaces.update(iface)

        return interfaces

    @property
    def bcache_info(self):
        if self._bcache_info:
            return self._bcache_info

        devs = []
        if not self.udevadm_db:
            return devs

        s = FileSearcher()
        sdef = SequenceSearchDef(start=SearchDef(r"^P: .+/(bcache\S+)"),
                                 body=SearchDef(r"^S: disk/by-uuid/(\S+)"),
                                 tag="bcacheinfo")
        s.add_search_term(sdef, self.udevadm_db)
        results = s.search()
        for section in results.find_sequence_sections(sdef).values():
            dev = {}
            for r in section:
                if r.tag == sdef.start_tag:
                    dev["name"] = r.get(1)
                else:
                    dev["by-uuid"] = r.get(1)

            devs.append(dev)

        self._bcache_info = devs
        return self._bcache_info

    def is_bcache_device(self, dev):
        """
        Returns True if the device either is or is based on a bcache device
        e.g. dmcrypt device using bcache dev.
        """
        if dev.startswith("bcache"):
            return True

        if dev.startswith("/dev/bcache"):
            return True

        ret = re.compile(r"/dev/mapper/crypt-(\S+)").search(dev)
        if ret:
            for dev in self.bcache_info:
                if dev.get("by-uuid") == ret.group(1):
                    return True

    def daemon_pkg_version(self, daemon):
        """Get version of local daemon based on package installed.

        This is prone to inaccuracy since the deamom many not have been
        restarted after package update.
        """
        pkginfo = checks.APTPackageChecksBase(CEPH_PKGS_CORE)
        return pkginfo.get_version(daemon)

    @property
    def osd_ids(self):
        """Return list of ceph-osd ids."""
        ceph_osds = self.services.get("ceph-osd")
        if not ceph_osds:
            return []

        osd_ids = []
        for cmd in ceph_osds["ps_cmds"]:
            ret = re.compile(r".+\s+.*--id\s+([0-9]+)\s+.+").match(cmd)
            if ret:
                osd_ids.append(int(ret[1]))

        return osd_ids


class CephChecksBase(CephBase, plugintools.PluginPartBase,
                     checks.ServiceChecksBase):

    def __init__(self, *args, **kwargs):
        super().__init__(service_exprs=CEPH_SERVICES_EXPRS, *args, **kwargs)

    @property
    def output(self):
        if self._output:
            return {"ceph": self._output}


class CephEventChecksBase(CephBase, checks.EventChecksBase):

    @property
    def output(self):
        if self._output:
            return {"ceph": self._output}


class BcacheBase(StorageBase):

    def get_sysfs_cachesets(self):
        cachesets = []
        path = os.path.join(constants.DATA_ROOT, "sys/fs/bcache/*")
        for entry in glob.glob(path):
            if os.path.exists(os.path.join(entry, "cache_available_percent")):
                cachesets.append({"path": entry,
                                  "uuid": os.path.basename(entry)})

        for cset in cachesets:
            path = os.path.join(cset['path'], "cache_available_percent")
            with open(path) as fd:
                value = fd.read().strip()
                cset["cache_available_percent"] = int(value)

            # dont include in final output
            del cset["path"]

        return cachesets


class BcacheChecksBase(BcacheBase, plugintools.PluginPartBase):

    @property
    def output(self):
        if self._output:
            return {"bcache": self._output}
