# coding=utf-8
__author__ = "Daniel Arroyo <daniel@3dagogo.com>"
__license__ = 'GNU Affero General Public License http://www.gnu.org/licenses/agpl.html'

import logging
import netifaces
import sarge
import os
import threading
import gobject

gobject.threads_init()

from dbus.exceptions import DBusException

from astroprint.network import NetworkManager as NetworkManagerBase

logger = logging.getLogger(__name__)

from tempfile import mkstemp
from shutil import move
from os import remove, close

class NetworkManagerEvents(threading.Thread):
	def __init__(self, NetworkManager):
		super(NetworkManagerEvents, self).__init__()
		self.daemon = True
		self._nm = NetworkManager

		NetworkManager.NetworkManager.connect_to_signal('PropertiesChanged', self.propertiesChanged)

	def run(self):
		gobject.idle_add(logger.info, 'NetworkManagerEvents is listening for signals')
		gobject.MainLoop().run()

	def propertiesChanged(self, properties):
		if "ActiveConnections" in properties and len(properties['ActiveConnections']) == 0:
			gobject.idle_add(logger.warn, "No active connections")
		
		if "State" in properties:
			gobject.idle_add(logger.info, "Network State Changed to (%s)" % self._nm.const('state', properties['State']))

class UbuntuNetworkManager(NetworkManagerBase):
	def __init__(self):
		super(UbuntuNetworkManager, self).__init__()

		#This needs to happen before importing NetworkManager
		from dbus.mainloop.glib import DBusGMainLoop, threads_init

		DBusGMainLoop(set_as_default=True)

		import NetworkManager

		threads_init()
		self._nm = NetworkManager
		self._eventListener = NetworkManagerEvents(self._nm)
		self._eventListener.start()

	def getWifiNetworks(self):
		interface = self.settings.get(['wifi', 'internetInterface'])
		wifiDevice = self._nm.NetworkManager.GetDeviceByIpIface(interface).SpecificDevice()

		networks = [{
			'id': ap.HwAddress,
			'signal': ord(ap.Strength),
			'name': ap.Ssid,
			'secured': True if ap.WpaFlags or ap.RsnFlags else False} for ap in wifiDevice.GetAccessPoints()]

		return networks

	def getActiveWifiNetwork(self):
		interface = self.settings.get(['wifi', 'internetInterface'])
		wifiDevice = self._nm.NetworkManager.GetDeviceByIpIface(interface)
		connection = wifiDevice.ActiveConnection

		if connection != '/':
			ap = connection.SpecificObject
			network = {
				'id': ap.HwAddress,
				'signal': ord(ap.Strength),
				'name': ap.Ssid,
				'ip': wifiDevice.Ip4Address,
				'secured': True if ap.WpaFlags or ap.RsnFlags else False}

			return network

		else:
			return False

	def setWifiNetwork(self, bssid, password = None):
		if bssid:
			interface = self.settings.get(['wifi','internetInterface'])
			wifiDevice = self._nm.NetworkManager.GetDeviceByIpIface(interface)

			accessPoint = None

			for ap in wifiDevice.SpecificDevice().GetAccessPoints():
				if ap.HwAddress == bssid:
					accessPoint = ap
					break

			if accessPoint:
				ssid = accessPoint.Ssid
				connection = None
				for c in self._nm.Settings.ListConnections():
					if c.GetSettings()['connection']['id'] == ssid:
						connection = c
						break

				try:
					if connection:
						self._nm.NetworkManager.ActivateConnection(connection, wifiDevice, "/")
					else:
						options = {
							'connection': {
								'id': ssid
							}
						}

						if password:
							options['802-11-wireless-security'] = {
								'psk': password
							}

						(connection, activeConnection) = self._nm.NetworkManager.AddAndActivateConnection(options, wifiDevice, accessPoint)

				except DBusException as e:
					if e.get_dbus_name() == 'org.freedesktop.NetworkManager.InvalidProperty' and e.get_dbus_message() == 'psk':
						return {'message': 'Invalid Password'}
					else:
						raise

				import gobject
				loop = gobject.MainLoop()

				result = {}

				def connectionStateChange(new_state, old_state, reason):
					r = result
					if new_state == self._nm.NM_DEVICE_STATE_ACTIVATED:
						result['ssid'] = ssid
						loop.quit()
					elif new_state == self._nm.NM_DEVICE_STATE_FAILED:
						connection.Delete()
						result['message'] = "The connection could not be created"
						loop.quit()

				wifiDevice.connect_to_signal('StateChanged', connectionStateChange)

				loop.run()

				return result

		return None

	def isHotspotActive(self):
		interface = self.settings.get(['wifi', 'hotspotInterface'])

		info = netifaces.ifaddresses(interface)

		return netifaces.AF_INET in info

	def startHotspot(self):
		try:
			p = sarge.run("service wifi_access_point start", stderr=sarge.Capture())
			if p.returncode != 0:
				returncode = p.returncode
				stderr_text = p.stderr.text
				logger.warn("Start hotspot failed with return code %i: %s" % (returncode, stderr_text))
				return "Start hotspot failed with return code %i: %s" % (returncode, stderr_text)
			else:
				return True

		except Exception, e:
			logger.warn("Start hotspot failed with return code: %s" % e)
			return "Start hotspot failed with return code: %s" % e

	def stopHotspot(self):
		try:
			p = sarge.run("service wifi_access_point stop", stderr=sarge.Capture())
			if p.returncode != 0:
				returncode = p.returncode
				stderr_text = p.stderr.text
				logger.warn("Stop hotspot failed with return code %i: %s" % (returncode, stderr_text))
				return "Stop hotspot failed with return code %i: %s" % (returncode, stderr_text)
			else:
				return True

		except Exception, e:
			logger.warn("Stop hotspot failed with return code: %s" % e)
			return "Stop hotspot failed with return code: %s" % e

	def getHostname(self):
		return self._nm.Settings.Hostname

	def setHostname(self, name):
		settings = self._nm.Settings

		old_name = settings.Hostname

		settings.SaveHostname(name)

		if (settings.Hostname == name):
			def replace(file_path, pattern, subst):
				#Create temp file
				fh, abs_path = mkstemp()
				new_file = open(abs_path,'w')
				old_file = open(file_path)
				for line in old_file:
					new_file.write(line.replace(pattern, subst))
				#close temp file
				new_file.close()
				close(fh)
				old_file.close()
				#Remove original file
				remove(file_path)
				#Move new file
				move(abs_path, file_path)
			
			udpateFiles = [
				'/etc/hosts'
			]

			for f in udpateFiles:
				if (os.path.exists(f) and os.path.isfile(f)):
					replace(f, old_name, name)

			return True

		else:
			return False

	def getMacAddress(self, interface = None):
		import md5

		device = None
		if interface:
			device = self._nm.NetworkManager.GetDeviceByIpIface(interface).SpecificDevice()
		else:
			#look at the first wired interface
			for dev in self._nm.NetworkManager.GetDevices():
				if dev.DeviceType == self._nm.NM_DEVICE_TYPE_ETHERNET:
					device = dev.SpecificDevice()
					break

		return md5.new(device.PermHwAddress).hexdigest() if device else None
