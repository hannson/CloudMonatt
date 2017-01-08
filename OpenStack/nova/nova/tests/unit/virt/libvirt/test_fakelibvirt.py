#    Copyright 2010 OpenStack Foundation
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from lxml import etree
import six

from nova.compute import arch
from nova import test
import nova.tests.unit.virt.libvirt.fakelibvirt as libvirt


def get_vm_xml(name="testname", uuid=None, source_type='file',
               interface_type='bridge'):
    uuid_tag = ''
    if uuid:
        uuid_tag = '<uuid>%s</uuid>' % (uuid,)

    return '''<domain type='kvm'>
  <name>%(name)s</name>
%(uuid_tag)s
  <memory>128000</memory>
  <vcpu>1</vcpu>
  <os>
    <type>hvm</type>
    <kernel>/somekernel</kernel>
    <cmdline>root=/dev/sda</cmdline>
    <boot dev='hd'/>
  </os>
  <features>
    <acpi/>
  </features>
  <devices>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2'/>
      <source %(source_type)s='/somefile'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <interface type='%(interface_type)s'>
      <mac address='05:26:3e:31:28:1f'/>
      <source %(interface_type)s='br100'/>
    </interface>
    <input type='mouse' bus='ps2'/>
    <graphics type='vnc' port='5901' autoport='yes' keymap='en-us'/>
    <graphics type='spice' port='5901' autoport='yes' keymap='en-us'/>
  </devices>
</domain>''' % {'name': name,
                'uuid_tag': uuid_tag,
                'source_type': source_type,
                'interface_type': interface_type}


class FakeLibvirtTests(test.NoDBTestCase):
    def tearDown(self):
        super(FakeLibvirtTests, self).tearDown()
        libvirt._reset()

    def get_openAuth_curry_func(self, readOnly=False):
        def fake_cb(credlist):
            return 0

        creds = [[libvirt.VIR_CRED_AUTHNAME,
                  libvirt.VIR_CRED_NOECHOPROMPT],
                  fake_cb,
                  None]
        flags = 0
        if readOnly:
            flags = libvirt.VIR_CONNECT_RO
        return lambda uri: libvirt.openAuth(uri, creds, flags)

    def test_openAuth_accepts_None_uri_by_default(self):
        conn_method = self.get_openAuth_curry_func()
        conn = conn_method(None)
        self.assertNotEqual(conn, None, "Connecting to fake libvirt failed")

    def test_openAuth_can_refuse_None_uri(self):
        conn_method = self.get_openAuth_curry_func()
        libvirt.allow_default_uri_connection = False
        self.addCleanup(libvirt._reset)
        self.assertRaises(ValueError, conn_method, None)

    def test_openAuth_refuses_invalid_URI(self):
        conn_method = self.get_openAuth_curry_func()
        self.assertRaises(libvirt.libvirtError, conn_method, 'blah')

    def test_getInfo(self):
        conn_method = self.get_openAuth_curry_func(readOnly=True)
        res = conn_method(None).getInfo()
        self.assertIn(res[0], (arch.I686, arch.X86_64))
        self.assertTrue(1024 <= res[1] <= 16384,
                        "Memory unusually high or low.")
        self.assertTrue(1 <= res[2] <= 32,
                        "Active CPU count unusually high or low.")
        self.assertTrue(800 <= res[3] <= 4500,
                        "CPU speed unusually high or low.")
        self.assertLessEqual(res[2], (res[5] * res[6]), "More active CPUs "
                             "than num_sockets*cores_per_socket")

    def test_createXML_detects_invalid_xml(self):
        self._test_XML_func_detects_invalid_xml('createXML', [0])

    def test_defineXML_detects_invalid_xml(self):
        self._test_XML_func_detects_invalid_xml('defineXML', [])

    def _test_XML_func_detects_invalid_xml(self, xmlfunc_name, args):
        conn = self.get_openAuth_curry_func()('qemu:///system')
        try:
            getattr(conn, xmlfunc_name)("this is not valid </xml>", *args)
        except libvirt.libvirtError as e:
            self.assertEqual(e.get_error_code(), libvirt.VIR_ERR_XML_DETAIL)
            self.assertEqual(e.get_error_domain(), libvirt.VIR_FROM_DOMAIN)
            return
        raise self.failureException("Invalid XML didn't raise libvirtError")

    def test_defineXML_defines_domain(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')
        conn.defineXML(get_vm_xml())
        dom = conn.lookupByName('testname')
        self.assertEqual('testname', dom.name())
        self.assertEqual(0, dom.isActive())
        dom.undefine()
        self.assertRaises(libvirt.libvirtError,
                          conn.lookupByName,
                          'testname')

    def test_blockStats(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')
        conn.createXML(get_vm_xml(), 0)
        dom = conn.lookupByName('testname')
        blockstats = dom.blockStats('vda')
        self.assertEqual(len(blockstats), 5)
        for x in blockstats:
            self.assertIn(type(x), six.integer_types)

    def test_attach_detach(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')
        conn.createXML(get_vm_xml(), 0)
        dom = conn.lookupByName('testname')
        xml = '''<disk type='block'>
                   <driver name='qemu' type='raw'/>
                   <source dev='/dev/nbd0'/>
                   <target dev='/dev/vdc' bus='virtio'/>
                 </disk>'''
        self.assertTrue(dom.attachDevice(xml))
        self.assertTrue(dom.detachDevice(xml))

    def test_info(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')
        conn.createXML(get_vm_xml(), 0)
        dom = conn.lookupByName('testname')
        info = dom.info()
        self.assertEqual(info[0], libvirt.VIR_DOMAIN_RUNNING)
        self.assertEqual(info[1], 128000)
        self.assertLessEqual(info[2], 128000)
        self.assertEqual(info[3], 1)
        self.assertIn(type(info[4]), six.integer_types)

    def test_createXML_runs_domain(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')
        conn.createXML(get_vm_xml(), 0)
        dom = conn.lookupByName('testname')
        self.assertEqual('testname', dom.name())
        self.assertEqual(1, dom.isActive())
        dom.destroy()
        try:
            conn.lookupByName('testname')
        except libvirt.libvirtError as e:
            self.assertEqual(e.get_error_code(), libvirt.VIR_ERR_NO_DOMAIN)
            self.assertEqual(e.get_error_domain(), libvirt.VIR_FROM_QEMU)
            return
        self.fail("lookupByName succeeded for destroyed non-defined VM")

    def test_defineXML_remembers_uuid(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')
        uuid = 'b21f957d-a72f-4b93-b5a5-45b1161abb02'
        conn.defineXML(get_vm_xml(uuid=uuid))
        dom = conn.lookupByName('testname')
        self.assertEqual(dom.UUIDString(), uuid)

    def test_createWithFlags(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')
        conn.defineXML(get_vm_xml())
        dom = conn.lookupByName('testname')
        self.assertFalse(dom.isActive(), 'Defined domain was running.')
        dom.createWithFlags(0)
        self.assertTrue(dom.isActive(),
                        'Domain wasn\'t running after createWithFlags')

    def test_managedSave(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')
        conn.defineXML(get_vm_xml())
        dom = conn.lookupByName('testname')
        self.assertFalse(dom.isActive(), 'Defined domain was running.')
        dom.createWithFlags(0)
        self.assertEqual(dom.hasManagedSaveImage(0), 0)
        dom.managedSave(0)
        self.assertEqual(dom.hasManagedSaveImage(0), 1)
        dom.managedSaveRemove(0)
        self.assertEqual(dom.hasManagedSaveImage(0), 0)

    def test_listDomainsId_and_lookupById(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')
        self.assertEqual(conn.listDomainsID(), [])
        conn.defineXML(get_vm_xml())
        dom = conn.lookupByName('testname')
        dom.createWithFlags(0)
        self.assertEqual(len(conn.listDomainsID()), 1)

        dom_id = conn.listDomainsID()[0]
        self.assertEqual(conn.lookupByID(dom_id), dom)

        dom_id = conn.listDomainsID()[0]
        try:
            conn.lookupByID(dom_id + 1)
        except libvirt.libvirtError as e:
            self.assertEqual(e.get_error_code(), libvirt.VIR_ERR_NO_DOMAIN)
            self.assertEqual(e.get_error_domain(), libvirt.VIR_FROM_QEMU)
            return
        raise self.failureException("Looking up an invalid domain ID didn't "
                                    "raise libvirtError")

    def test_define_and_retrieve(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')
        self.assertEqual(conn.listDomainsID(), [])
        conn.defineXML(get_vm_xml())
        dom = conn.lookupByName('testname')
        xml = dom.XMLDesc(0)
        etree.fromstring(xml)

    def _test_accepts_source_type(self, source_type):
        conn = self.get_openAuth_curry_func()('qemu:///system')
        self.assertEqual(conn.listDomainsID(), [])
        conn.defineXML(get_vm_xml(source_type=source_type))
        dom = conn.lookupByName('testname')
        xml = dom.XMLDesc(0)
        tree = etree.fromstring(xml)
        elem = tree.find('./devices/disk/source')
        self.assertEqual(elem.get('file'), '/somefile')

    def test_accepts_source_dev(self):
        self._test_accepts_source_type('dev')

    def test_accepts_source_path(self):
        self._test_accepts_source_type('path')

    def test_network_type_bridge_sticks(self):
        self._test_network_type_sticks('bridge')

    def test_network_type_network_sticks(self):
        self._test_network_type_sticks('network')

    def _test_network_type_sticks(self, network_type):
        conn = self.get_openAuth_curry_func()('qemu:///system')
        self.assertEqual(conn.listDomainsID(), [])
        conn.defineXML(get_vm_xml(interface_type=network_type))
        dom = conn.lookupByName('testname')
        xml = dom.XMLDesc(0)
        tree = etree.fromstring(xml)
        elem = tree.find('./devices/interface')
        self.assertEqual(elem.get('type'), network_type)
        elem = elem.find('./source')
        self.assertEqual(elem.get(network_type), 'br100')

    def test_getType(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')
        self.assertEqual(conn.getType(), 'QEMU')

    def test_getVersion(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')
        self.assertIsInstance(conn.getVersion(), int)

    def test_getCapabilities(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')
        etree.fromstring(conn.getCapabilities())

    def test_nwfilter_define_undefine(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')
        # Will raise an exception if it's not valid XML
        xml = '''<filter name='nova-instance-instance-789' chain='root'>
                    <uuid>946878c6-3ad3-82b2-87f3-c709f3807f58</uuid>
                 </filter>'''

        conn.nwfilterDefineXML(xml)
        nwfilter = conn.nwfilterLookupByName('nova-instance-instance-789')
        nwfilter.undefine()
        try:
            conn.nwfilterLookupByName('nova-instance-instance-789320334')
        except libvirt.libvirtError as e:
            self.assertEqual(e.get_error_code(), libvirt.VIR_ERR_NO_NWFILTER)
            self.assertEqual(e.get_error_domain(), libvirt.VIR_FROM_NWFILTER)
            return
        raise self.failureException("Invalid NWFilter name didn't"
                                    " raise libvirtError")

    def test_compareCPU_compatible(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')

        xml = '''<cpu>
                   <arch>%s</arch>
                   <model>%s</model>
                   <vendor>%s</vendor>
                   <topology sockets="%d" cores="%d" threads="%d"/>
                 </cpu>''' % (conn.host_info.arch,
                              conn.host_info.cpu_model,
                              conn.host_info.cpu_vendor,
                              conn.host_info.cpu_sockets,
                              conn.host_info.cpu_cores,
                              conn.host_info.cpu_threads)
        self.assertEqual(conn.compareCPU(xml, 0),
                         libvirt.VIR_CPU_COMPARE_IDENTICAL)

    def test_compareCPU_incompatible_vendor(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')

        xml = '''<cpu>
                   <arch>%s</arch>
                   <model>%s</model>
                   <vendor>%s</vendor>
                   <topology sockets="%d" cores="%d" threads="%d"/>
                 </cpu>''' % (conn.host_info.arch,
                              conn.host_info.cpu_model,
                              "AnotherVendor",
                              conn.host_info.cpu_sockets,
                              conn.host_info.cpu_cores,
                              conn.host_info.cpu_threads)
        self.assertEqual(conn.compareCPU(xml, 0),
                         libvirt.VIR_CPU_COMPARE_INCOMPATIBLE)

    def test_compareCPU_incompatible_arch(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')

        xml = '''<cpu>
                   <arch>%s</arch>
                   <model>%s</model>
                   <vendor>%s</vendor>
                   <topology sockets="%d" cores="%d" threads="%d"/>
                 </cpu>''' % ('not-a-valid-arch',
                              conn.host_info.cpu_model,
                              conn.host_info.cpu_vendor,
                              conn.host_info.cpu_sockets,
                              conn.host_info.cpu_cores,
                              conn.host_info.cpu_threads)
        self.assertEqual(conn.compareCPU(xml, 0),
                         libvirt.VIR_CPU_COMPARE_INCOMPATIBLE)

    def test_compareCPU_incompatible_model(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')

        xml = '''<cpu>
                   <arch>%s</arch>
                   <model>%s</model>
                   <vendor>%s</vendor>
                   <topology sockets="%d" cores="%d" threads="%d"/>
                 </cpu>''' % (conn.host_info.arch,
                              "AnotherModel",
                              conn.host_info.cpu_vendor,
                              conn.host_info.cpu_sockets,
                              conn.host_info.cpu_cores,
                              conn.host_info.cpu_threads)
        self.assertEqual(conn.compareCPU(xml, 0),
                         libvirt.VIR_CPU_COMPARE_INCOMPATIBLE)

    def test_compareCPU_compatible_unspecified_model(self):
        conn = self.get_openAuth_curry_func()('qemu:///system')

        xml = '''<cpu>
                   <arch>%s</arch>
                   <vendor>%s</vendor>
                   <topology sockets="%d" cores="%d" threads="%d"/>
                 </cpu>''' % (conn.host_info.arch,
                              conn.host_info.cpu_vendor,
                              conn.host_info.cpu_sockets,
                              conn.host_info.cpu_cores,
                              conn.host_info.cpu_threads)
        self.assertEqual(conn.compareCPU(xml, 0),
                         libvirt.VIR_CPU_COMPARE_IDENTICAL)

    def test_numa_topology_generation(self):
        topology = """<topology>
  <cells num="2">
    <cell id="0">
      <memory unit="KiB">7870000</memory>
      <pages size="4" unit="KiB">1967500</pages>
      <cpus num="4">
        <cpu id="0" socket_id="0" core_id="0" siblings="0-1"/>
        <cpu id="1" socket_id="0" core_id="0" siblings="0-1"/>
        <cpu id="2" socket_id="0" core_id="1" siblings="2-3"/>
        <cpu id="3" socket_id="0" core_id="1" siblings="2-3"/>
      </cpus>
    </cell>
    <cell id="1">
      <memory unit="KiB">7870000</memory>
      <pages size="4" unit="KiB">1967500</pages>
      <cpus num="4">
        <cpu id="4" socket_id="1" core_id="0" siblings="4-5"/>
        <cpu id="5" socket_id="1" core_id="0" siblings="4-5"/>
        <cpu id="6" socket_id="1" core_id="1" siblings="6-7"/>
        <cpu id="7" socket_id="1" core_id="1" siblings="6-7"/>
      </cpus>
    </cell>
  </cells>
</topology>
"""
        host_topology = libvirt.HostInfo._gen_numa_topology(
                                               cpu_nodes=2, cpu_sockets=1,
                                               cpu_cores=2, cpu_threads=2,
                                               kb_mem=15740000)
        self.assertEqual(host_topology.to_xml(),
                         topology)