"""Unit and integration tests for Admin API endpoints, passcode authentication, and database fallback resilience."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)
PASS = settings.admin_password or "tandev6546"
HEADERS = {"X-Admin-Password": PASS}


class TestAdminPasswordAuth:
    def test_unauthenticated_admin_stats_rejected(self):
        """Unauthenticated GET /admin/stats must return 401 Unauthorized."""
        res = client.get("/admin/stats")
        assert res.status_code == 401

    def test_unauthenticated_delete_document_rejected(self):
        """Unauthenticated DELETE /admin/documents/{id} must return 401 Unauthorized."""
        res = client.delete("/admin/documents/sample_doc")
        assert res.status_code == 401

    def test_verify_admin_password_endpoint(self):
        """POST /admin/verify verifies admin password correctly."""
        res_correct = client.post("/admin/verify", json={"password": PASS})
        assert res_correct.status_code == 200
        assert res_correct.json()["valid"] is True

    def test_five_failed_attempts_locks_out(self):
        """5 failed attempts trigger 429 Too Many Requests lockout."""
        from app.api.admin import _LOGIN_ATTEMPTS
        _LOGIN_ATTEMPTS.clear()

        # Submit 4 wrong attempts
        for i in range(4):
            res = client.post("/admin/verify", json={"password": "bad_pass_test"})
            assert res.status_code == 401
            assert "attempt(s) remaining" in res.json()["detail"]

        # 5th wrong attempt triggers 429 lockout
        res5 = client.post("/admin/verify", json={"password": "bad_pass_test"})
        assert res5.status_code == 429
        assert "locked" in res5.json()["detail"].lower()

        # Cleanup attempts dict after test
        _LOGIN_ATTEMPTS.clear()


class TestAdminEndpoints:
    def test_admin_stats_structure(self):
        """Test that /admin/stats returns valid schema structure when authenticated."""
        res = client.get("/admin/stats", headers=HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert "documents" in data
        assert "total_documents" in data
        assert "total_chunks" in data
        assert "total_nodes" in data
        assert "total_edges" in data
        assert "config" in data
        assert "llm" in data["config"]
        assert "embeddings" in data["config"]

    @patch("app.api.admin.user_db._get_db")
    @patch("app.api.admin.user_db.user_stats", return_value={"total_users": 0})
    @patch("app.api.admin.fallback_graph.admin_documents", return_value={"documents": [], "total_entities": 0, "total_relationships": 0})
    @patch("app.api.admin.neo4j_driver")
    def test_admin_stats_fallback_on_neo4j_error(self, mock_driver, mock_fg, mock_us, mock_udb):
        """Test that /admin/stats returns fallback zeros gracefully when Neo4j is offline."""
        mock_driver.side_effect = Exception("Neo4j Connection Failed")
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_udb.return_value.__enter__.return_value = mock_conn
        res = client.get("/admin/stats", headers=HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert data["total_documents"] == 0
        assert data["total_chunks"] == 0
        assert data["total_nodes"] == 0
        assert data["total_edges"] == 0
        assert "config" in data



    @patch("app.api.admin.vectorstore.delete_by_document")
    @patch("app.api.admin.graphrag.delete_by_document")
    def test_delete_document_success(self, mock_graph_del, mock_vec_del):
        """Test deleting a document via /admin/documents/{id} with admin authentication."""
        mock_vec_del.return_value = 5
        mock_graph_del.return_value = {"nodes_deleted": 3, "rels_deleted": 4}
        
        doc_id = "doc_test_123"
        res = client.delete(f"/admin/documents/{doc_id}", headers=HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "deleted"
        assert data["document_id"] == doc_id
        assert data["vectors_deleted"] == 5
        assert data["graph_stats"] == {"nodes_deleted": 3, "rels_deleted": 4}


class TestAdminConfigSanity:
    def test_config_keys_present(self):
        res = client.get("/admin/stats", headers=HEADERS)
        assert res.status_code == 200
        cfg = res.json()["config"]
        assert "embed_dim" in cfg
        assert "rerank_floor" in cfg
        assert "top_k" in cfg
        assert "graph_fanout" in cfg
