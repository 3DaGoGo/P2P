# coding=utf-8
__author__ = "Daniel Arroyo <daniel@astroprint.com>"
__license__ = 'GNU Affero General Public License http://www.gnu.org/licenses/agpl.html'

from flask import request, jsonify

from octoprint.server.api import api
from octoprint.server import restricted_access

from astroprint.printerprofile import printerProfileManager
from astroprint.printer.manager import printerManager


@api.route('/printer-profile', methods=['PATCH', 'GET'])
def printer_profile_patch():
	ppm = printerProfileManager()

	if request.method == "PATCH":
		changes = request.json
		if changes.get('check_clear_bed') is False and ppm.data.get('check_clear_bed') is True:
			printerManager().set_bed_clear(True)
		ppm.set(changes)
		ppm.save()

		return jsonify()

	else:

		result = ppm.data.copy()
		result.update( {"driverChoices": ppm.driverChoices()} )

		return jsonify( result )

@api.route('/temperature-preset', methods=['POST'])
@restricted_access
def temp_preset_create():
	ppm = printerProfileManager()

	name = request.values.get('name', None)
	nozzle_temp = request.values.get('nozzle_temp', None)
	bed_temp = request.values.get('bed_temp', None)

	return jsonify( {'id' : ppm.createTempPreset(name, nozzle_temp, bed_temp)} )
