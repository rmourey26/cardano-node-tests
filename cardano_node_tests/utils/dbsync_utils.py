"""Functionality for interacting with db-sync."""
import logging
from typing import Dict
from typing import List
from typing import NamedTuple
from typing import Optional

import psycopg2
from cardano_clusterlib import clusterlib

from cardano_node_tests.utils import clusterlib_utils
from cardano_node_tests.utils import configuration

LOGGER = logging.getLogger(__name__)


DBSYNC_DB = "dbsync"


class TxDBRecord(NamedTuple):
    tx_id: int
    tx_hash: str
    block_id: int
    block_index: int
    out_sum: int
    fee: int
    deposit: int
    size: int
    invalid_before: Optional[int]
    invalid_hereafter: Optional[int]
    txouts: List[clusterlib.UTXOData]
    mint: List[clusterlib.UTXOData]


class QueryRow(NamedTuple):
    tx_id: int
    tx_hash: memoryview
    block_id: int
    block_index: int
    out_sum: int
    fee: int
    deposit: int
    size: int
    invalid_before: Optional[int]
    invalid_hereafter: Optional[int]
    tx_out_id: int
    tx_out_tx_id: int
    utxo_ix: int
    tx_out_addr: str
    tx_out_value: int
    ma_tx_out_id: Optional[int]
    ma_tx_out_policy: Optional[memoryview]
    ma_tx_out_name: Optional[memoryview]
    ma_tx_out_quantity: Optional[int]
    ma_tx_mint_id: Optional[int]
    ma_tx_mint_policy: Optional[memoryview]
    ma_tx_mint_name: Optional[memoryview]
    ma_tx_mint_quantity: Optional[int]


class DBSync:
    conn_cache: Optional[psycopg2.extensions.connection] = None

    @classmethod
    def conn(cls) -> psycopg2.extensions.connection:
        if cls.conn_cache is None or cls.conn_cache.closed == 1:
            cls.conn_cache = psycopg2.connect(f"dbname={DBSYNC_DB}")
        return cls.conn_cache


def query_tx(
    cluster_obj: clusterlib.ClusterLib, tx_raw_output: clusterlib.TxRawOutput
) -> TxDBRecord:
    """Query a transaction in db-sync."""
    body_txid = cluster_obj.get_txid_body(tx_raw_output.out_file)

    with DBSync.conn().cursor() as cur:
        cur.execute(
            "SELECT"
            " tx.id, tx.hash, tx.block_id, tx.block_index, tx.out_sum, tx.fee, tx.deposit, tx.size,"
            " tx.invalid_before, tx.invalid_hereafter,"
            " tx_out.id, tx_out.tx_id, tx_out.index, tx_out.address, tx_out.value,"
            " ma_tx_out.id, ma_tx_out.policy, ma_tx_out.name, ma_tx_out.quantity,"
            " ma_tx_mint.id, ma_tx_mint.policy, ma_tx_mint.name, ma_tx_mint.quantity "
            "FROM tx "
            "LEFT JOIN tx_out ON tx.id = tx_out.tx_id "
            "LEFT JOIN ma_tx_out ON tx_out.id = ma_tx_out.tx_out_id "
            "LEFT JOIN ma_tx_mint ON tx.id = ma_tx_mint.tx_id "
            "WHERE tx.hash = %s;",
            (rf"\x{body_txid}",),
        )
        results = cur.fetchall()

    if not results:
        raise RuntimeError("No results were returned by the SQL query.")

    utxo_out: List[clusterlib.UTXOData] = []
    seen_tx_out_ids = set()
    ma_utxo_out: List[clusterlib.UTXOData] = []
    seen_ma_tx_out_ids = set()
    mint_utxo_out: List[clusterlib.UTXOData] = []
    seen_ma_tx_mint_ids = set()

    for r in results:
        query_row = QueryRow(*r)

        # Lovelace outputs
        if query_row.tx_out_id and query_row.tx_out_id not in seen_tx_out_ids:
            seen_tx_out_ids.add(query_row.tx_out_id)
            out_rec = clusterlib.UTXOData(
                utxo_hash=str(body_txid),
                utxo_ix=str(query_row.utxo_ix),
                amount=int(query_row.tx_out_value),
                address=str(query_row.tx_out_addr),
            )
            utxo_out.append(out_rec)

        # MA outputs
        if query_row.ma_tx_out_id and query_row.ma_tx_out_id not in seen_ma_tx_out_ids:
            seen_ma_tx_out_ids.add(query_row.ma_tx_out_id)
            asset_name = (
                bytearray.fromhex(query_row.ma_tx_out_name.hex()).decode()
                if query_row.ma_tx_out_name
                else None
            )
            policyid = query_row.ma_tx_out_policy.hex() if query_row.ma_tx_out_policy else ""
            coin = f"{policyid}.{asset_name}" if asset_name else policyid
            ma_rec = clusterlib.UTXOData(
                utxo_hash=str(body_txid),
                utxo_ix=str(query_row.utxo_ix),
                amount=int(query_row.ma_tx_out_quantity or 0),
                address=str(query_row.tx_out_addr),
                coin=coin,
            )
            ma_utxo_out.append(ma_rec)

        # MA minting
        if query_row.ma_tx_mint_id and query_row.ma_tx_mint_id not in seen_ma_tx_mint_ids:
            seen_ma_tx_mint_ids.add(query_row.ma_tx_mint_id)
            asset_name = (
                bytearray.fromhex(query_row.ma_tx_mint_name.hex()).decode()
                if query_row.ma_tx_mint_name
                else None
            )
            policyid = query_row.ma_tx_mint_policy.hex() if query_row.ma_tx_mint_policy else ""
            coin = f"{policyid}.{asset_name}" if asset_name else policyid
            mint_rec = clusterlib.UTXOData(
                utxo_hash=str(body_txid),
                utxo_ix=str(query_row.utxo_ix),
                amount=int(query_row.ma_tx_mint_quantity or 0),
                address=str(query_row.tx_out_addr),
                coin=coin,
            )
            mint_utxo_out.append(mint_rec)

    record = TxDBRecord(
        tx_id=int(query_row.tx_id),
        tx_hash=query_row.tx_hash.hex(),
        block_id=int(query_row.block_id),
        block_index=int(query_row.block_index),
        out_sum=int(query_row.out_sum),
        fee=int(query_row.fee),
        deposit=int(query_row.deposit),
        size=int(query_row.size),
        invalid_before=int(query_row.invalid_before) if query_row.invalid_before else None,
        invalid_hereafter=int(query_row.invalid_hereafter) if query_row.invalid_hereafter else None,
        txouts=[*utxo_out, *ma_utxo_out],
        mint=mint_utxo_out,
    )

    return record


def check_tx(
    cluster_obj: clusterlib.ClusterLib, tx_raw_output: clusterlib.TxRawOutput
) -> Optional[TxDBRecord]:
    """Check a transaction in db-sync."""
    if not configuration.HAS_DBSYNC:
        return None

    response = query_tx(cluster_obj=cluster_obj, tx_raw_output=tx_raw_output)

    txouts_amount = clusterlib_utils.get_amount(tx_raw_output.txouts)
    assert (
        response.out_sum == txouts_amount
    ), f"Sum of TX amounts doesn't match ({response.out_sum} != {txouts_amount})"
    assert (
        response.fee == tx_raw_output.fee
    ), f"TX fee doesn't match ({response.fee} != {tx_raw_output.fee})"
    assert response.invalid_before == tx_raw_output.invalid_before, (
        "TX invalid_before doesn't match "
        f"({response.invalid_before} != {tx_raw_output.invalid_before})"
    )
    assert response.invalid_hereafter == tx_raw_output.invalid_hereafter, (
        "TX invalid_hereafter doesn't match "
        f"({response.invalid_hereafter} != {tx_raw_output.invalid_hereafter})"
    )
    len_db_txouts, len_out_txouts = len(response.txouts), len(tx_raw_output.txouts)
    assert (
        len_db_txouts == len_out_txouts
    ), f"Number of TX outputs doesn't match ({len_db_txouts} != {len_out_txouts})"

    # calculate minting amount sum for records with same address and token
    mint_txouts: Dict[str, clusterlib.TxOut] = {}
    for mt in tx_raw_output.mint:
        mt_id = f"{mt.address}_{mt.coin}"
        if mt_id in mint_txouts:
            mt_stored = mint_txouts[mt_id]
            mint_txouts[mt_id] = mt_stored._replace(amount=mt_stored.amount + mt.amount)
        else:
            mint_txouts[mt_id] = mt
    len_db_mint, len_out_mint = len(response.mint), len(mint_txouts.values())
    assert (
        len_db_mint == len_out_mint
    ), f"Number of MA minting doesn't match ({len_db_mint} != {len_out_mint})"

    return response
