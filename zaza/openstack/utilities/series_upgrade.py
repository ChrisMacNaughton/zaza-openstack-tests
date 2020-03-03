# Copyright 2020 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Collection of functions for testing series upgrade."""

import logging
import os

from zaza import model
from zaza.charm_lifecycle import utils as cl_utils
import zaza.openstack.utilities.generic as os_utils


SUBORDINATE_PAUSE_RESUME_BLACKLIST = [
    "cinder-ceph",
]


def run_post_upgrade_functions(post_upgrade_functions):
    """Execute list supplied functions.

    :param post_upgrade_functions: List of functions
    :type post_upgrade_functions: [function, function, ...]
    """
    if post_upgrade_functions:
        for func in post_upgrade_functions:
            logging.info("Running {}".format(func))
            cl_utils.get_class(func)()


def series_upgrade_non_leaders_first(application, from_series="trusty",
                                     to_series="xenial",
                                     completed_machines=[],
                                     post_upgrade_functions=None):
    """Series upgrade non leaders first.

    Wrap all the functionality to handle series upgrade for charms
    which must have non leaders upgraded first.

    :param application: Name of application to upgrade series
    :type application: str
    :param from_series: The series from which to upgrade
    :type from_series: str
    :param to_series: The series to which to upgrade
    :type to_series: str
    :param completed_machines: List of completed machines which do no longer
                               require series upgrade.
    :type completed_machines: list
    :returns: None
    :rtype: None
    """
    status = model.get_status().applications[application]
    leader = None
    non_leaders = []
    for unit in status["units"]:
        if status["units"][unit].get("leader"):
            leader = unit
        else:
            non_leaders.append(unit)

    # Series upgrade the non-leaders first
    for unit in non_leaders:
        machine = status["units"][unit]["machine"]
        if machine not in completed_machines:
            logging.info("Series upgrade non-leader unit: {}"
                         .format(unit))
            series_upgrade(unit, machine,
                           from_series=from_series, to_series=to_series,
                           origin=None,
                           post_upgrade_functions=post_upgrade_functions)
            run_post_upgrade_functions(post_upgrade_functions)
            completed_machines.append(machine)
        else:
            logging.info("Skipping unit: {}. Machine: {} already upgraded. "
                         .format(unit, machine, application))
            model.block_until_all_units_idle()

    # Series upgrade the leader
    machine = status["units"][leader]["machine"]
    logging.info("Series upgrade leader: {}".format(leader))
    if machine not in completed_machines:
        series_upgrade(leader, machine,
                       from_series=from_series, to_series=to_series,
                       origin=None,
                       post_upgrade_functions=post_upgrade_functions)
        completed_machines.append(machine)
    else:
        logging.info("Skipping unit: {}. Machine: {} already upgraded."
                     .format(unit, machine, application))
        model.block_until_all_units_idle()


def series_upgrade_application(application, pause_non_leader_primary=True,
                               pause_non_leader_subordinate=True,
                               from_series="trusty", to_series="xenial",
                               origin='openstack-origin',
                               completed_machines=[],
                               files=None, workaround_script=None,
                               post_upgrade_functions=None):
    """Series upgrade application.

    Wrap all the functionality to handle series upgrade for a given
    application. Including pausing non-leader units.

    :param application: Name of application to upgrade series
    :type application: str
    :param pause_non_leader_primary: Whether the non-leader applications should
                                     be paused
    :type pause_non_leader_primary: bool
    :param pause_non_leader_subordinate: Whether the non-leader subordinate
                                         hacluster applications should be
                                         paused
    :type pause_non_leader_subordinate: bool
    :param from_series: The series from which to upgrade
    :type from_series: str
    :param to_series: The series to which to upgrade
    :type to_series: str
    :param origin: The configuration setting variable name for changing origin
                   source. (openstack-origin or source)
    :type origin: str
    :param completed_machines: List of completed machines which do no longer
                               require series upgrade.
    :type completed_machines: list
    :param files: Workaround files to scp to unit under upgrade
    :type files: list
    :param workaround_script: Workaround script to run during series upgrade
    :type workaround_script: str
    :returns: None
    :rtype: None
    """
    status = model.get_status().applications[application]

    # For some applications (percona-cluster) the leader unit must upgrade
    # first. For API applications the non-leader haclusters must be paused
    # before upgrade. Finally, for some applications this is arbitrary but
    # generalized.
    leader = None
    non_leaders = []
    for unit in status["units"]:
        if status["units"][unit].get("leader"):
            leader = unit
        else:
            non_leaders.append(unit)

    # Pause the non-leaders
    for unit in non_leaders:
        if pause_non_leader_subordinate:
            if status["units"][unit].get("subordinates"):
                for subordinate in status["units"][unit]["subordinates"]:
                    _app = subordinate.split('/')[0]
                    if _app in SUBORDINATE_PAUSE_RESUME_BLACKLIST:
                        logging.info("Skipping pausing {} - blacklisted"
                                     .format(subordinate))
                    else:
                        logging.info("Pausing {}".format(subordinate))
                        model.run_action(
                            subordinate, "pause", action_params={})
        if pause_non_leader_primary:
            logging.info("Pausing {}".format(unit))
            model.run_action(unit, "pause", action_params={})

    machine = status["units"][leader]["machine"]
    # Series upgrade the leader
    logging.info("Series upgrade leader: {}".format(leader))
    if machine not in completed_machines:
        series_upgrade(leader, machine,
                       from_series=from_series, to_series=to_series,
                       origin=origin, workaround_script=workaround_script,
                       files=files,
                       post_upgrade_functions=post_upgrade_functions)
        completed_machines.append(machine)
    else:
        logging.info("Skipping unit: {}. Machine: {} already upgraded."
                     "But setting origin on the application {}"
                     .format(unit, machine, application))
        logging.info("Set origin on {}".format(application))
        os_utils.set_origin(application, origin)
        model.block_until_all_units_idle()

    # Series upgrade the non-leaders
    for unit in non_leaders:
        machine = status["units"][unit]["machine"]
        if machine not in completed_machines:
            logging.info("Series upgrade non-leader unit: {}"
                         .format(unit))
            series_upgrade(unit, machine,
                           from_series=from_series, to_series=to_series,
                           origin=origin, workaround_script=workaround_script,
                           files=files,
                           post_upgrade_functions=post_upgrade_functions)
            completed_machines.append(machine)
        else:
            logging.info("Skipping unit: {}. Machine: {} already upgraded. "
                         "But setting origin on the application {}"
                         .format(unit, machine, application))
            logging.info("Set origin on {}".format(application))
            os_utils.set_origin(application, origin)
            model.block_until_all_units_idle()


def series_upgrade(unit_name, machine_num,
                   from_series="trusty", to_series="xenial",
                   origin='openstack-origin',
                   files=None, workaround_script=None,
                   post_upgrade_functions=None):
    """Perform series upgrade on a unit.

    :param unit_name: Unit Name
    :type unit_name: str
    :param machine_num: Machine number
    :type machine_num: str
    :param from_series: The series from which to upgrade
    :type from_series: str
    :param to_series: The series to which to upgrade
    :type to_series: str
    :param origin: The configuration setting variable name for changing origin
                   source. (openstack-origin or source)
    :type origin: str
    :param files: Workaround files to scp to unit under upgrade
    :type files: list
    :param workaround_script: Workaround script to run during series upgrade
    :type workaround_script: str
    :returns: None
    :rtype: None
    """
    logging.info("Series upgrade {}".format(unit_name))
    application = unit_name.split('/')[0]
    os_utils.set_dpkg_non_interactive_on_unit(unit_name)
    dist_upgrade(unit_name)
    model.block_until_all_units_idle()
    logging.info("Prepare series upgrade on {}".format(machine_num))
    model.prepare_series_upgrade(machine_num, to_series=to_series)
    logging.info("Waiting for workload status 'blocked' on {}"
                 .format(unit_name))
    model.block_until_unit_wl_status(unit_name, "blocked")
    logging.info("Waiting for model idleness")
    model.block_until_all_units_idle()
    wrap_do_release_upgrade(unit_name, from_series=from_series,
                            to_series=to_series, files=files,
                            workaround_script=workaround_script)
    logging.info("Reboot {}".format(unit_name))
    os_utils.reboot(unit_name)
    logging.info("Waiting for workload status 'blocked' on {}"
                 .format(unit_name))
    model.block_until_unit_wl_status(unit_name, "blocked")
    logging.info("Waiting for model idleness")
    model.block_until_all_units_idle()
    logging.info("Set origin on {}".format(application))
    # Allow for charms which have neither source nor openstack-origin
    if origin:
        os_utils.set_origin(application, origin)
    model.block_until_all_units_idle()
    logging.info("Complete series upgrade on {}".format(machine_num))
    model.complete_series_upgrade(machine_num)
    model.block_until_all_units_idle()
    logging.info("Running run_post_upgrade_functions {}".format(
        post_upgrade_functions))
    run_post_upgrade_functions(post_upgrade_functions)
    logging.info("Waiting for workload status 'active' on {}"
                 .format(unit_name))
    model.block_until_unit_wl_status(unit_name, "active")
    model.block_until_all_units_idle()
    # This step may be performed by juju in the future
    logging.info("Set series on {} to {}".format(application, to_series))
    model.set_series(application, to_series)


def wrap_do_release_upgrade(unit_name, from_series="trusty",
                            to_series="xenial",
                            files=None, workaround_script=None):
    """Wrap do release upgrade.

    In a production environment this step would be run administratively.
    For testing purposes we need this automated.

    :param unit_name: Unit Name
    :type unit_name: str
    :param from_series: The series from which to upgrade
    :type from_series: str
    :param to_series: The series to which to upgrade
    :type to_series: str
    :param files: Workaround files to scp to unit under upgrade
    :type files: list
    :param workaround_script: Workaround script to run during series upgrade
    :type workaround_script: str
    :returns: None
    :rtype: None
    """
    # Pre upgrade hacks
    # There are a few necessary hacks to accomplish an automated upgrade
    # to overcome some packaging bugs.
    # Copy scripts
    if files:
        logging.info("SCP files")
        for _file in files:
            logging.info("SCP {}".format(_file))
            model.scp_to_unit(unit_name, _file, os.path.basename(_file))

    # Run Script
    if workaround_script:
        logging.info("Running workaround script")
        os_utils.run_via_ssh(unit_name, workaround_script)

    # Actually do the do_release_upgrade
    do_release_upgrade(unit_name)


def dist_upgrade(unit_name):
    """Run dist-upgrade on unit after update package db.

    :param unit_name: Unit Name
    :type unit_name: str
    :returns: None
    :rtype: None
    """
    logging.info('Updating package db ' + unit_name)
    update_cmd = 'sudo apt update'
    model.run_on_unit(unit_name, update_cmd)

    logging.info('Updating existing packages ' + unit_name)
    dist_upgrade_cmd = (
        """sudo DEBIAN_FRONTEND=noninteractive apt --assume-yes """
        """-o "Dpkg::Options::=--force-confdef" """
        """-o "Dpkg::Options::=--force-confold" dist-upgrade""")
    model.run_on_unit(unit_name, dist_upgrade_cmd)


def do_release_upgrade(unit_name):
    """Run do-release-upgrade noninteractive.

    :param unit_name: Unit Name
    :type unit_name: str
    :returns: None
    :rtype: None
    """
    logging.info('Upgrading ' + unit_name)
    # NOTE: It is necessary to run this via juju ssh rather than juju run due
    # to timeout restrictions and error handling.
    os_utils.run_via_ssh(
        unit_name,
        'DEBIAN_FRONTEND=noninteractive '
        'do-release-upgrade -f DistUpgradeViewNonInteractive')
