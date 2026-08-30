"""Guarda contra o Extrator computar metricas em vez de extrai-las.

No piloto ele emitiu `operating income margin = 18.4 PCT` com a evidencia
`"Operatingincome 1,306"` -- numero derivado (e errado) com evidencia de
numero bruto. Injetar erro num valor ja fabricado tornaria o ground truth da
perturbacao sem sentido.
"""

from __future__ import annotations

import pytest

from handoff.conditions import Stage
from handoff.injector import InjectionError, inject
from handoff.schemas.claims import CanonicalClaim
from handoff.serialization import value_in_evidence, verify_extraction


def claim(claim_id: str, value: float, evidence: str, unit: str = "USD_M") -> CanonicalClaim:
    return CanonicalClaim(
        claim_id=claim_id,
        metric="x",
        value=value,
        unit=unit,
        year=2019,
        source_id="doc",
        generated_by=Stage.EXTRACTOR,
        evidence=evidence,
    )


@pytest.mark.parametrize(
    "value,evidence,expected",
    [
        (1306.0, "Operatingincome\n \n1,306", True),
        (39403.0, "Revenue $ 39,403", True),
        (12.4, "Revenue for fiscal 2026 was $12.4 million", True),
        (8.1, "operating margin of 8.1%", True),
        # o caso real do piloto: margem computada, evidencia do numero bruto
        (18.4, "Operatingincome\n \n1,306", False),
        (11.4, "Netsales 11,503", False),
        (100.0, "", False),
        # negativo em notacao contabil: capex aparece entre parenteses
        (-1577.0, "Purchases of property, plant and equipment (PP&E)\n\n(1,577)", True),
        (-270579.0, "Capitalexpenditures,netofconstructionpayable\n(270,579)", True),
        (-116.0, "Capital expenditures\n(116) \n(131)", True),
    ],
)
def test_value_in_evidence(value, evidence, expected):
    assert value_in_evidence(value, evidence) is expected


def test_verify_extraction_separa_verificados():
    claims = [
        claim("C01", 1306.0, "Operatingincome 1,306"),
        claim("C02", 18.4, "Operatingincome 1,306", unit="PCT"),
    ]
    eligible, report = verify_extraction(claims)
    assert eligible == {"C01"}
    assert [r["value_in_evidence"] for r in report] == [True, False]


def test_injecao_nao_mira_claim_fabricado():
    claims = [
        claim("C01", 18.4, "Operatingincome 1,306"),  # fabricado
        claim("C02", 11503.0, "Netsales 11,503"),  # verificado
    ]
    eligible, _ = verify_extraction(claims)
    _, record = inject(claims, "value", eligible_ids=eligible)
    assert record.target_claim_id == "C02"


def test_sem_claim_verificado_a_injecao_falha_alto():
    claims = [claim("C01", 18.4, "Operatingincome 1,306")]
    eligible, _ = verify_extraction(claims)
    with pytest.raises(InjectionError, match="verificado"):
        inject(claims, "value", eligible_ids=eligible)
