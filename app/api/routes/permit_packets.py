from fastapi import APIRouter, Response

from app.schemas.permits import EvJobRequest
from app.services.permits.ev_charger import EvJob, EvPacket, build_ev_packet
from app.services.permits.ev_packet_pdf import render_ev_packet_pdf
from app.services.permits.load_calculation import HomeLoads

router = APIRouter(prefix="/api/permit-packets", tags=["permit-packets"])


def _packet(payload: EvJobRequest) -> EvPacket:
    fields = payload.model_dump(exclude={"home"})
    return build_ev_packet(EvJob(home=HomeLoads(**payload.home.model_dump()), **fields))


@router.post("/ev/check")
def check_ev_job(payload: EvJobRequest) -> dict:
    packet = _packet(payload)
    circuit = packet.circuit
    return {
        "ready": packet.ready,
        "computed_amps": round(packet.load.computed_amps, 1),
        "total_va": round(packet.load.total_va),
        "spare_amps": round(packet.load.spare_amps, 1),
        "breaker": circuit.breaker,
        "wire": f"#{circuit.wire.size} AWG Cu",
        "ground": f"#{circuit.ground} AWG Cu",
        "voltage_drop_percent": round(circuit.voltage_drop_percent, 1),
        "underground_conduit": packet.underground_conduit,
        "interior_conduit": packet.interior_conduit,
        "disconnect_amps": packet.disconnect_amps,
        "checks": [
            {"name": check.name, "result": check.result, "passed": check.passed}
            for check in packet.checks
        ],
        "flags": packet.flags,
    }


@router.post("/ev/pdf")
def ev_packet_pdf(payload: EvJobRequest) -> Response:
    return Response(
        content=render_ev_packet_pdf(_packet(payload)),
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="ev-permit-packet-demo.pdf"',
            "Cache-Control": "private, no-store",
        },
    )
