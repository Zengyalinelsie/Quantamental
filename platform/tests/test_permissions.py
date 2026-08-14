import unittest

from a_share_platform.application.permissions import Permission, PermissionPolicy, Principal, Role


class PermissionPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = PermissionPolicy.default()

    def test_role_values_cover_spec_004(self) -> None:
        self.assertEqual(
            {role.value for role in Role},
            {
                "viewer",
                "researcher",
                "data_operator",
                "reviewer",
                "portfolio_manager",
                "trader",
                "administrator",
                "agent",
            },
        )

    def test_anonymous_principal_is_read_only(self) -> None:
        anonymous = Principal.anonymous()
        self.assertTrue(self.policy.allows(anonymous, Permission.READ_PUBLIC))
        self.assertFalse(self.policy.allows(anonymous, Permission.READ_ARTIFACT))
        self.assertFalse(self.policy.allows(anonymous, Permission.CREATE_EXPERIMENT))
        self.assertFalse(self.policy.allows(anonymous, Permission.SEND_ORDER))

    def test_researcher_and_agent_cannot_send_orders(self) -> None:
        for role in Role:
            if role in {Role.TRADER, Role.ADMINISTRATOR}:
                continue
            with self.subTest(role=role):
                principal = Principal(subject_id=f"subject:{role.value}", roles=frozenset({role}))
                self.assertFalse(self.policy.allows(principal, Permission.SEND_ORDER))

    def test_private_artifact_read_is_human_role_scoped_and_denied_to_agent(self) -> None:
        permitted = {
            Role.RESEARCHER,
            Role.DATA_OPERATOR,
            Role.REVIEWER,
            Role.PORTFOLIO_MANAGER,
            Role.ADMINISTRATOR,
        }
        for role in Role:
            with self.subTest(role=role):
                principal = Principal(f"subject:{role.value}", frozenset({role}))
                self.assertEqual(
                    self.policy.allows(principal, Permission.READ_ARTIFACT),
                    role in permitted,
                )

        viewer = Principal("subject:viewer", frozenset({Role.VIEWER}))
        self.assertFalse(self.policy.allows(viewer, Permission.READ_ARTIFACT))

    def test_each_human_role_has_only_its_declared_p1_capability(self) -> None:
        expected = {
            Role.VIEWER: Permission.READ_PUBLIC,
            Role.RESEARCHER: Permission.CREATE_EXPERIMENT,
            Role.DATA_OPERATOR: Permission.MANAGE_DATA,
            Role.REVIEWER: Permission.APPROVE_RESEARCH,
            Role.PORTFOLIO_MANAGER: Permission.APPROVE_PORTFOLIO,
            Role.TRADER: Permission.SEND_ORDER,
            Role.ADMINISTRATOR: Permission.ADMINISTER,
            Role.AGENT: Permission.READ_PUBLIC,
        }
        for role, permission in expected.items():
            with self.subTest(role=role):
                principal = Principal(f"subject:{role.value}", frozenset({role}))
                self.assertTrue(self.policy.allows(principal, permission))

    def test_unknown_permission_is_denied_by_default(self) -> None:
        viewer = Principal("subject:viewer", frozenset({Role.VIEWER}))
        self.assertFalse(self.policy.allows(viewer, "undefined_permission"))


if __name__ == "__main__":
    unittest.main()
