#!/usr/bin/env python3

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

"""Encapsulate Cinder testing."""

import logging

import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.ceph as ceph_utils
import zaza.openstack.utilities.openstack as openstack_utils


class CinderTests(test_utils.OpenStackBaseTest):
    """Encapsulate Cinder Ceph functional tests."""

    RESOURCE_PREFIX = 'zaza-cinder'

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(CinderTests, cls).setUpClass()
        cls.cinder_client = openstack_utils.get_cinder_session_client(
            cls.keystone_session)

    def test_409_ceph_check_osd_pools(self):
        """Verify that the expected Ceph pools are present."""
        expected_pools = ceph_utils.get_expected_pools()
        results = []
        unit_name = 'ceph-mon/0'

        # Check for presence of expected pools on each unit
        logging.debug('Expected pools: {}'.format(expected_pools))
        pools = ceph_utils.get_ceph_pools(unit_name)
        results.append(pools)

        self.assertEqual(expected_pools, results)

    def test_410_ceph_cinder_vol_create_pool_inspect(self):
        """Validate that cinder volummes appear on ceph."""
        unit_name = zaza.model.get_lead_unit_name('ceph-mon')
        obj_count_samples = []
        pool_size_samples = []
        pools = ceph_utils.get_ceph_pools(unit_name)
        expected_pool = 'cinder-ceph'
        cinder_ceph_pool = pools[expected_pool]

        # Check ceph cinder pool object count, disk space usage and pool name
        logging.info('Checking ceph cinder pool original samples...')
        pool_name, obj_count, kb_used = ceph_utils.get_ceph_pool_sample(
            unit_name, cinder_ceph_pool)

        obj_count_samples.append(obj_count)
        pool_size_samples.append(kb_used)

        self.assertEqual(pool_name, expected_pool)

        # Create ceph-backed cinder volume
        cinder_vol = self.cinder_client.volumes.create(
            name='{}-410-vol'.format(self.RESOURCE_PREFIX),
            size=1)

        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            cinder_vol.id,
            wait_iteration_max_time=180,
            stop_after_attempt=15,
            expected_status='available',
            msg='Volume status wait')

        logging.info('Checking ceph cinder pool samples after volume create')
        pool_name, obj_count, kb_used = ceph_utils.get_ceph_pool_sample(
            unit_name, cinder_ceph_pool)

        obj_count_samples.append(obj_count)
        pool_size_samples.append(kb_used)

        # Delete the volume
        openstack_utils.delete_volume(self.cinder_client, cinder_vol.id)

        # Re-check ceph cinder pool object count and disk usage
        logging.info('Checking ceph cinder pool samples '
                     'after volume create...')
        pool_name, obj_count, kb_used = ceph_utils.get_ceph_pool_sample(
            unit_name, cinder_ceph_pool)

        obj_count_samples.append(obj_count)
        pool_size_samples.append(kb_used)

        # Luminous (pike) ceph seems more efficient at disk usage so we cannot
        # grantee the ordering of kb_used
        if openstack_utils.get_os_release() < \
                openstack_utils.get_os_release('xenial_mitaka'):
            # Validate ceph cinder pool disk space usage samples over time
            original, created, deleted = range(3)
            self.assertLessEqual(
                pool_size_samples[created],
                pool_size_samples[original],
                "Original sample had more objects")
            self.assertMoreEqual(
                pool_size_samples[deleted],
                pool_size_samples[created],
                "Final sample had more objects")
