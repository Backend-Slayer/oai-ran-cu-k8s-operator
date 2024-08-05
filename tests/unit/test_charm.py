#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import patch

import pytest
from charm import OAIRANCUOperatorCharm
from lightkube.models.apps_v1 import StatefulSetSpec
from lightkube.models.core_v1 import (
    Container,
    PodSpec,
    PodTemplateSpec,
    SecurityContext,
)
from lightkube.models.meta_v1 import LabelSelector
from lightkube.resources.apps_v1 import StatefulSet
from ops import testing
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus

GNB_IDENTITY_LIB = "charms.sdcore_gnbsim_k8s.v0.fiveg_gnb_identity.GnbIdentityProvides"
NAMESPACE = "whatever"
WORKLOAD_CONTAINER_NAME = "cu"


class TestCharm:
    patcher_lightkube_client = patch("lightkube.core.client.GenericSyncClient")
    patcher_lightkube_client_get = patch("lightkube.core.client.Client.get")
    patcher_lightkube_client_replace = patch("lightkube.core.client.Client.replace")
    patcher_k8s_service_patch = patch("charm.KubernetesServicePatch")
    patcher_gnb_identity = patch(f"{GNB_IDENTITY_LIB}.publish_gnb_identity_information")
    patcher_check_output = patch("charm.check_output")

    @pytest.fixture()
    def setUp(self):
        self.mock_lightkube_client = TestCharm.patcher_lightkube_client.start()
        self.mock_lightkube_client_get = TestCharm.patcher_lightkube_client_get.start()
        self.mock_lightkube_client_replace = TestCharm.patcher_lightkube_client_replace.start()
        self.mock_k8s_service_patch = TestCharm.patcher_k8s_service_patch.start()
        self.mock_gnb_identity = TestCharm.patcher_gnb_identity.start()
        self.mock_check_output = TestCharm.patcher_check_output.start()

    def tearDown(self) -> None:
        patch.stopall()

    @pytest.fixture(autouse=True)
    def harness(self, setUp, request):
        self.harness = testing.Harness(OAIRANCUOperatorCharm)
        self.harness.set_model_name(name=NAMESPACE)
        self.harness.set_leader(is_leader=True)
        self.harness.set_can_connect(container=WORKLOAD_CONTAINER_NAME, val=True)
        self.harness.begin()
        yield self.harness
        self.harness.cleanup()
        request.addfinalizer(self.tearDown)

    def test_given_unit_is_not_leader_when_config_changed_then_status_is_blocked(self):
        self.harness.set_leader(is_leader=False)
        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == BlockedStatus(
            "Scaling is not implemented for this charm"
        )

    @pytest.mark.parametrize(
        "config_param,value",
        [
            pytest.param("f1-interface-name", "", id="empty_f1_interface_name"),
            pytest.param("f1-port", int(), id="empty_f1_port"),
            pytest.param("n2-interface-name", "", id="empty_n2_interface_name"),
            pytest.param("n3-interface-name", "", id="empty_n3_interface_name"),
            pytest.param("mcc", "", id="empty_mcc"),
            pytest.param("mnc", "", id="empty_mnc"),
            pytest.param("sst", int(), id="empty_sst"),
            pytest.param("tac", int(), id="empty_tac"),

        ],
    )
    def test_given_invalid_config_when_config_changed_then_status_is_blocked(
        self, config_param, value
    ):
        self.harness.update_config(key_values={config_param: value})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == BlockedStatus(
            f"The following configurations are not valid: ['{config_param}']"
        )

    def test_given_n2_relation_not_created_when_config_changed_then_status_is_blocked(self):
        self.harness.set_leader(is_leader=True)
        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == BlockedStatus(
            "Waiting for N2 relation to be created"
        )

    def test_given_workload_container_cant_be_connected_to_when_config_changed_then_status_is_waiting(  # noqa: E501
        self,
    ):
        self.create_n2_relation()
        self.harness.set_can_connect(container=WORKLOAD_CONTAINER_NAME, val=False)
        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == WaitingStatus("Waiting for container to be ready")

    def test_given_charm_statefulset_is_not_patched_when_config_changed_then_status_is_waiting(
        self,
    ):
        test_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="whatever",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=WORKLOAD_CONTAINER_NAME,
                                securityContext=SecurityContext(privileged=False),
                            )
                        ]
                    )
                ),
            )
        )
        self.mock_lightkube_client_get.return_value = test_statefulset
        self.create_n2_relation()
        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == WaitingStatus(
            "Waiting for statefulset to be patched"
        )

    def test_give_storage_is_not_attached_when_config_changed_then_status_is_waiting(self):
        test_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="whatever",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=WORKLOAD_CONTAINER_NAME,
                                securityContext=SecurityContext(privileged=True),
                            )
                        ]
                    )
                ),
            )
        )
        self.mock_lightkube_client_get.return_value = test_statefulset
        self.create_n2_relation()
        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == WaitingStatus(
            "Waiting for storage to be attached"
        )

    def test_given_amf_n2_information_is_not_available_when_config_changed_then_status_is_waiting(
        self,
    ):
        test_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="whatever",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=WORKLOAD_CONTAINER_NAME,
                                securityContext=SecurityContext(privileged=True),
                            )
                        ]
                    )
                ),
            )
        )
        self.mock_lightkube_client_get.return_value = test_statefulset
        self.harness.add_storage("config", attach=True)
        self.create_n2_relation()
        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == WaitingStatus("Waiting for N2 information")

    def test_given_all_status_check_are_ok_when_config_changed_then_status_is_active(self):
        test_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="whatever",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=WORKLOAD_CONTAINER_NAME,
                                securityContext=SecurityContext(privileged=True),
                            )
                        ]
                    )
                ),
            )
        )
        self.mock_lightkube_client_get.return_value = test_statefulset
        self.mock_check_output.return_value = b'1.1.1.1'
        self.harness.add_storage("config", attach=True)
        self.set_n2_relation_data()
        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == ActiveStatus()

    def create_n2_relation(self) -> int:
        """Create a relation between the CU and the AMF.

        Returns:
            int: ID of the created relation
        """
        amf_relation_id = self.harness.add_relation(relation_name="fiveg_n2", remote_app="amf")  # type: ignore[attr-defined]  # noqa: E501
        self.harness.add_relation_unit(relation_id=amf_relation_id, remote_unit_name="amf/0")  # type: ignore[attr-defined]  # noqa: E501
        return amf_relation_id

    def set_n2_relation_data(self) -> int:
        """Create the N2 relation, set the relation data in the n2 relation and return its ID.

        Returns:
            int: ID of the created relation
        """
        amf_relation_id = self.create_n2_relation()
        self.harness.update_relation_data(  # type: ignore[attr-defined]
            relation_id=amf_relation_id,
            app_or_unit="amf",
            key_values={
                "amf_hostname": "amf",
                "amf_port": "38412",
                "amf_ip_address": "1.1.1.1",
            },
        )
        return amf_relation_id
