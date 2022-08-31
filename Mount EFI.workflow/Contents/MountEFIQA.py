#!/usr/bin/env python

import subprocess, plistlib, sys, os, shlex

class Disk:

    def __init__(self):
        self.diskutil = "diskutil" # self.get_diskutil()
        self.os_version = self.run(["sw_vers", "-productVersion"])[0].strip()
        self.sudo_mount_version = "10.13.6"
        self.sudo_mount_types   = ["efi"]
        self.apfs = {}
        self._update_disks()

    def run(self, comm, shell = False):
        c = None
        try:
            if shell and type(comm) is list:    comm = " ".join(shlex.quote(x) for x in comm)
            if not shell and type(comm) is str: comm = shlex.split(comm)
            p = subprocess.Popen(comm, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            c = p.communicate()
        except:
            if c == None: return ("", "Command not found!", 1)
        return (self._get_str(c[0]), self._get_str(c[1]), p.returncode)

    def _get_str(self, val):
        # Helper method to return a string value based on input type
        if sys.version_info >= (3,0) and isinstance(val, bytes): return val.decode("utf-8")
        return val

    def _get_plist(self, s):
        p = {}
        try:
            if sys.version_info >= (3, 0):
                p = plistlib.loads(s.encode("utf-8"))
            else:
                # We avoid using readPlistFromString() as that uses
                # cStringIO and fails when Unicode strings are detected
                # Don't subclass - keep the parser local
                from xml.parsers.expat import ParserCreate
                # Create a new PlistParser object - then we need to set up
                # the values and parse.
                pa = plistlib.PlistParser()
                # We also monkey patch this to encode unicode as utf-8
                def end_string():
                    d = pa.getData()
                    if isinstance(d,unicode):
                        d = d.encode("utf-8")
                    pa.addObject(d)
                pa.end_string = end_string
                parser = ParserCreate()
                parser.StartElementHandler = pa.handleBeginElement
                parser.EndElementHandler = pa.handleEndElement
                parser.CharacterDataHandler = pa.handleData
                if isinstance(s, unicode):
                    # Encode unicode -> string; use utf-8 for safety
                    s = s.encode("utf-8")
                # Parse the string
                parser.Parse(s, 1)
                p = pa.root
        except Exception as e:
            print(e)
        return p

    def update(self):
        self._update_disks()

    def _update_disks(self):
        self.disks = self.get_disks()
        self.disk_text = self.get_disk_text()
        self.apfs = self.get_apfs() if self.os_version >= "10.12" else {}

    def get_disks(self):
        # Returns a dictionary object of connected disks
        disk_list = self.run([self.diskutil, "list", "-plist"])[0]
        return self._get_plist(disk_list)

    def get_disk_text(self):
        # Returns plain text listing connected disks
        return self.run([self.diskutil, "list"])[0]

    def get_apfs(self):
        # Returns a dictionary object of apfs disks
        output = self.run("echo y | " + self.diskutil + " apfs list -plist", True)
        if not output[2] == 0: return {} # Error getting apfs info - return an empty dict
        disk_list = output[0]
        p_list = disk_list.split("<?xml")
        if len(p_list) > 1: disk_list = "<?xml" + p_list[-1] # We had text before the start - get only the plist info
        return self._get_plist(disk_list)

    def is_apfs(self, disk):
        disk_id = self.get_identifier(disk)
        if not disk_id: return None
        # Takes a disk identifier, and returns whether or not it's apfs
        for d in self.disks.get("AllDisksAndPartitions", []):
            if not "APFSVolumes" in d: continue
            if d.get("DeviceIdentifier", "").lower() == disk_id.lower():
                return True
            for a in d.get("APFSVolumes", []):
                if a.get("DeviceIdentifier", "").lower() == disk_id.lower():
                    return True
        return False

    def is_apfs_container(self, disk):
        disk_id = self.get_identifier(disk)
        if not disk_id: return None
        # Takes a disk identifier, and returns whether or not that specific 
        # disk/volume is an APFS Container
        for d in self.disks.get("AllDisksAndPartitions", []):
            # Only check partitions
            for p in d.get("Partitions", []):
                if disk_id.lower() == p.get("DeviceIdentifier", "").lower():
                    return p.get("Content", "").lower() == "apple_apfs"
        return False

    def is_cs_container(self, disk):
        disk_id = self.get_identifier(disk)
        if not disk_id: return None
        # Takes a disk identifier, and returns whether or not that specific 
        # disk/volume is an CoreStorage Container
        for d in self.disks.get("AllDisksAndPartitions", []):
            # Only check partitions
            for p in d.get("Partitions", []):
                if disk_id.lower() == p.get("DeviceIdentifier", "").lower():
                    return p.get("Content", "").lower() == "apple_corestorage"
        return False

    def is_core_storage(self, disk):
        disk_id = self.get_identifier(disk)
        if not disk_id: return None
        if self._get_physical_disk(disk_id, "Logical Volume on "): return True
        return False

    def get_identifier(self, disk):
        # Should be able to take a mount point, disk name, or disk identifier,
        # and return the disk's identifier
        # Iterate!!
        if not disk or not len(self._get_str(disk)): return None
        disk = disk.lower()
        if disk.startswith("/dev/r"):  disk = disk[len("/dev/r"):]
        elif disk.startswith("/dev/"): disk = disk[len("/dev/"):]
        if disk in self.disks.get("AllDisks", []): return disk
        for d in self.disks.get("AllDisksAndPartitions", []):
            for a in d.get("APFSVolumes", []):
                if disk in [ a.get(x, "").lower() for x in ["DeviceIdentifier", "VolumeName", "VolumeUUID", "DiskUUID", "MountPoint"] ]:
                    return a.get("DeviceIdentifier", None)
            for a in d.get("Partitions", []):
                if disk in [ a.get(x, "").lower() for x in ["DeviceIdentifier", "VolumeName", "VolumeUUID", "DiskUUID", "MountPoint"] ]:
                    return a.get("DeviceIdentifier", None)
        # At this point, we didn't find it
        return None

    def get_top_identifier(self, disk):
        disk_id = self.get_identifier(disk)
        if not disk_id: return None
        return disk_id.replace("disk", "didk").split("s")[0].replace("didk", "disk")
        
    def _get_physical_disk(self, disk, search_term):
        # Change disk0s1 to disk0
        our_disk = self.get_top_identifier(disk)
        our_term = "/dev/" + our_disk
        found_disk = False
        our_text = ""
        for line in self.disk_text.split("\n"):
            if line.lower().startswith(our_term):
                found_disk = True
                continue
            if not found_disk: continue
            if line.lower().startswith("/dev/disk"):
                # At the next disk - bail
                break
            if search_term.lower() in line.lower():
                our_text = line
                break
        if not len(our_text): return None # Nothing found
        our_stores = "".join(our_text.strip().split(search_term)[1:]).split(" ,")
        if not len(our_stores): return None
        for store in our_stores:
            efi = self.get_efi(store)
            if efi: return store
        return None

    def get_physical_store(self, disk):
        # Returns the physical store containing the EFI
        disk_id = self.get_identifier(disk)
        if not disk_id or not self.is_apfs(disk_id): return None
        return self._get_physical_disk(disk_id, "Physical Store ")

    def get_core_storage_pv(self, disk):
        # Returns the core storage physical volume containing the EFI
        disk_id = self.get_identifier(disk)
        if not disk_id or not self.is_core_storage(disk_id): return None
        return self._get_physical_disk(disk_id, "Logical Volume on ")

    def get_parent(self, disk):
        # Disk can be a mount point, disk name, or disk identifier
        disk_id = self.get_identifier(disk)
        if self.is_apfs(disk_id): disk_id = self.get_physical_store(disk_id)
        elif self.is_core_storage(disk_id): disk_id = self.get_core_storage_pv(disk_id)
        if not disk_id: return None
        if self.is_apfs(disk_id):
            # We have apfs - let's get the container ref
            for a in self.apfs.get("Containers", []):
                # Check if it's the whole container
                if a.get("ContainerReference", "").lower() == disk_id.lower():
                    return a["ContainerReference"]
                # Check through each volume and return the parent's container ref
                for v in a.get("Volumes", []):
                    if v.get("DeviceIdentifier", "").lower() == disk_id.lower():
                        return a.get("ContainerReference", None)
        else:
            # Not apfs - go through all volumes and whole disks
            for d in self.disks.get("AllDisksAndPartitions", []):
                if d.get("DeviceIdentifier", "").lower() == disk_id.lower():
                    return d["DeviceIdentifier"]
                for p in d.get("Partitions", []):
                    if p.get("DeviceIdentifier", "").lower() == disk_id.lower():
                        return d["DeviceIdentifier"]
        # Didn't find anything
        return None

    def get_efi(self, disk):
        disk_id = self.get_parent(self.get_identifier(disk))
        if not disk_id: return None
        # At this point - we should have the parent
        for d in self.disks["AllDisksAndPartitions"]:
            if d.get("DeviceIdentifier", "").lower() == disk_id.lower():
                # Found our disk
                for p in d.get("Partitions", []):
                    if p.get("Content", "").lower() == "efi":
                        return p.get("DeviceIdentifier", None)
        return None

    def needs_sudo(self, disk_id = None):
        content = "EFI" # Default to EFI content
        if disk_id: content = self.get_content(disk_id)
        return self.os_version >= self.sudo_mount_version and content.lower() in self.sudo_mount_types

    def is_mounted(self, disk):
        disk_id = self.get_identifier(disk)
        if not disk_id: return None
        m = self.get_mount_point(disk_id)
        return (m != None and len(m)>0)

    def _get_value(self, disk, field, default = None, apfs_only = False):
        disk_id = self.get_identifier(disk)
        if not disk_id:
            return None
        # Takes a disk identifier, and returns the requested value
        for d in self.disks.get("AllDisksAndPartitions", []):
            for a in d.get("APFSVolumes", []):
                if a.get("DeviceIdentifier", "").lower() == disk_id.lower():
                    return a.get(field, default)
            if apfs_only:
                # Skip looking at regular partitions
                continue
            if d.get("DeviceIdentifier", "").lower() == disk_id.lower():
                return d.get(field, default)
            for a in d.get("Partitions", []):
                if a.get("DeviceIdentifier", "").lower() == disk_id.lower():
                    return a.get(field, default)
        return None

    # Getter methods
    def get_content(self, disk):
        return self._get_value(disk, "Content")
    
    def get_mount_point(self, disk):
        return self._get_value(disk, "MountPoint")

    def get_volume_name(self, disk):
        return self._get_value(disk, "VolumeName")

    def open_mount_point(self, disk, new_window = False):
        disk_id = self.get_identifier(disk)
        if not disk_id: return None
        mount = self.get_mount_point(disk_id)
        if not mount: return None
        out = self.run(["open", mount])
        return out[2] == 0

if __name__ == '__main__':
    d = Disk()
    # Gather the args
    errors = []
    args = []
    for x in sys.argv[1:]:
        if x == "/":
            args.append(x)
            continue
        if not x.lower().startswith("/volumes/"):
            errors.append("'{}' is not a volume.".format(x))
            continue
        if x.endswith("/"):
            x = x[:-1]
        if len(x.split("/")) > 3:
            # Too nested - not a volume
            errors.append("'{}' is not a volume.".format(x))
            continue
        if not os.path.exists(x):
            # Doesn't exist, skip it
            errors.append("'{}' does not exist.".format(x))
            continue
        args.append(x)
    mount_list = []
    needs_sudo = d.needs_sudo()
    for x in args:
        name = d.get_volume_name(x)
        if not name: name = "Untitled"
        name = name.replace('"','\\"') # Escape double quotes in names
        efi = d.get_efi(x)
        if efi: mount_list.append((efi,name,d.is_mounted(efi),"diskutil mount {}".format(efi)))
        else: errors.append("'{}' has no ESP.".format(name))
    if len(mount_list):
        # We have something to mount
        efis =  [x[-1] for x in mount_list if not x[2]] # Only mount those that aren't mounted
        names = [x[1]  for x in mount_list if not x[2]]
        if len(efis): # We have something to mount here
            command = "do shell script \"{}\" with prompt \"MountEFI would like to mount the ESP{} on {}\"{}".format(
                "; ".join(efis),
                "s" if len(names) > 1 else "",
                ", ".join(names),
                " with administrator privileges" if needs_sudo else "")
            o,e,r = d.run(["osascript","-e",command])
            if r > 0 and len(e.strip()) and e.strip().lower().endswith("(-128)"): exit() # User canceled, bail
            # Update the disks
            d.update()
        # Walk the mounts and find out which aren't mounted
        for efi,name,mounted,comm in mount_list:
            mounted_at = d.get_mount_point(efi)
            if mounted_at: d.open_mount_point(mounted_at)
            else: errors.append("ESP for '{}' failed to mount.".format(name))
    else:
        errors.append("No disks with ESPs selected.")
    if len(errors):
        # Display our errors before we leave
        d.run(["osascript","-e","display dialog \"{}\" buttons {{\"OK\"}} default button \"OK\" with icon caution".format("\n".join(errors))])