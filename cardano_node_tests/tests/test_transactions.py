import logging
import os

import pytest

from cardano_node_tests.utils.clusterlib import CLIError
from cardano_node_tests.utils.clusterlib import TxFiles
from cardano_node_tests.utils.clusterlib import TxIn
from cardano_node_tests.utils.clusterlib import TxOut
from cardano_node_tests.utils.helpers import create_payment_addrs
from cardano_node_tests.utils.helpers import create_stake_addrs
from cardano_node_tests.utils.helpers import fund_from_faucet

LOGGER = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def temp_dir(tmp_path_factory):
    curdir = os.getcwd()
    tmp_path = tmp_path_factory.mktemp("test_transactions")
    try:
        os.chdir(tmp_path)
        yield tmp_path
    finally:
        os.chdir(curdir)


pytestmark = pytest.mark.usefixtures("temp_dir")


class TestBasic:
    @pytest.fixture(scope="class")
    def payment_addrs(self, cluster_session, addrs_data_session, request):
        """Create 2 new payment addresses."""
        addrs = create_payment_addrs("addr_basic0", "addr_basic1", cluster_obj=cluster_session)

        # fund source addresses
        fund_from_faucet(
            addrs[0],
            cluster_obj=cluster_session,
            faucet_data=addrs_data_session["user1"],
            request=request,
        )

        return addrs

    def test_transfer_funds(self, cluster_session, addrs_data_session, payment_addrs):
        """Send funds from faucet to payment address."""
        cluster = cluster_session
        amount = 2000

        src_address = addrs_data_session["user1"]["payment_addr"]
        dst_address = payment_addrs[0].address

        src_init_balance = cluster.get_address_balance(src_address)
        dst_init_balance = cluster.get_address_balance(dst_address)

        destinations = [TxOut(address=dst_address, amount=amount)]
        tx_files = TxFiles(
            signing_key_files=[addrs_data_session["user1"]["payment_key_pair"].skey_file]
        )

        tx_raw_data = cluster.send_funds(
            src_address=src_address, destinations=destinations, tx_files=tx_files,
        )
        cluster.wait_for_new_tip(new_blocks=2)

        assert (
            cluster.get_address_balance(src_address)
            == src_init_balance - tx_raw_data.fee - len(destinations) * amount
        ), f"Incorrect balance for source address `{src_address}`"

        assert (
            cluster.get_address_balance(dst_address) == dst_init_balance + amount
        ), f"Incorrect balance for destination address `{dst_address}`"

    def test_transfer_all_funds(self, cluster_session, payment_addrs):
        """Send ALL funds from one payment address to another."""
        cluster = cluster_session

        src_address = payment_addrs[0].address
        dst_address = payment_addrs[1].address

        src_init_balance = cluster.get_address_balance(src_address)
        dst_init_balance = cluster.get_address_balance(dst_address)

        # amount value -1 means all available funds
        destinations = [TxOut(address=payment_addrs[1].address, amount=-1)]
        tx_files = TxFiles(signing_key_files=[payment_addrs[0].skey_file])

        tx_raw_data = cluster.send_funds(
            src_address=src_address, destinations=destinations, tx_files=tx_files,
        )
        cluster.wait_for_new_tip(new_blocks=2)

        assert (
            cluster.get_address_balance(src_address) == 0
        ), f"Incorrect balance for source address `{src_address}`"

        assert (
            cluster.get_address_balance(dst_address)
            == dst_init_balance + src_init_balance - tx_raw_data.fee
        ), f"Incorrect balance for destination address `{dst_address}`"


class Test10InOut:
    @pytest.fixture(scope="class")
    def payment_addrs(self, cluster_session, addrs_data_session, request):
        """Create 11 new payment addresses."""
        addrs = create_payment_addrs(
            *[f"addr_10_in_out{i}" for i in range(11)], cluster_obj=cluster_session,
        )

        # fund source addresses
        fund_from_faucet(
            addrs[0],
            cluster_obj=cluster_session,
            faucet_data=addrs_data_session["user1"],
            request=request,
        )

        return addrs

    def test_10_transactions(self, cluster_session, addrs_data_session, payment_addrs):
        """Send 10 transactions from faucet to payment address.

        Test 10 different UTXOs in addr0.
        """
        cluster = cluster_session
        no_of_transactions = len(payment_addrs) - 1

        src_address = addrs_data_session["user1"]["payment_addr"]
        dst_address = payment_addrs[0].address

        src_init_balance = cluster.get_address_balance(src_address)
        dst_init_balance = cluster.get_address_balance(dst_address)

        tx_files = TxFiles(
            signing_key_files=[addrs_data_session["user1"]["payment_key_pair"].skey_file]
        )
        ttl = cluster.calculate_tx_ttl()

        fee = cluster.calculate_tx_fee(
            src_address, dst_addresses=[dst_address], tx_files=tx_files, ttl=ttl,
        )
        amount = int(fee / no_of_transactions + 1000)
        destinations = [TxOut(address=dst_address, amount=amount)]

        for __ in range(no_of_transactions):
            cluster.send_funds(
                src_address=src_address,
                destinations=destinations,
                tx_files=tx_files,
                fee=fee,
                ttl=ttl,
            )
            cluster.wait_for_new_tip(new_blocks=2)

        assert (
            cluster.get_address_balance(src_address)
            == src_init_balance - fee * no_of_transactions - amount * no_of_transactions
        ), f"Incorrect balance for source address `{src_address}`"

        assert (
            cluster.get_address_balance(dst_address)
            == dst_init_balance + amount * no_of_transactions
        ), f"Incorrect balance for destination address `{dst_address}`"

    def test_transaction_to_10_addrs(self, cluster_session, payment_addrs):
        """Send 1 transaction from one payment address to 10 payment addresses."""
        cluster = cluster_session
        src_address = payment_addrs[0].address
        # addr1..addr10
        dst_addresses = [payment_addrs[i].address for i in range(1, len(payment_addrs))]

        src_init_balance = cluster.get_address_balance(src_address)
        dst_init_balances = {addr: cluster.get_address_balance(addr) for addr in dst_addresses}

        tx_files = TxFiles(signing_key_files=[payment_addrs[0].skey_file])
        ttl = cluster.calculate_tx_ttl()

        fee = cluster.calculate_tx_fee(
            src_address, dst_addresses=dst_addresses, tx_files=tx_files, ttl=ttl,
        )
        amount = int((cluster.get_address_balance(src_address) - fee) / len(dst_addresses))
        destinations = [TxOut(address=addr, amount=amount) for addr in dst_addresses]

        cluster.send_funds(
            src_address=src_address, destinations=destinations, tx_files=tx_files, fee=fee, ttl=ttl,
        )
        cluster.wait_for_new_tip(new_blocks=2)

        assert cluster.get_address_balance(src_address) == src_init_balance - fee - amount * len(
            dst_addresses
        ), f"Incorrect balance for source address `{src_address}`"

        for addr in dst_addresses:
            assert (
                cluster.get_address_balance(addr) == dst_init_balances[addr] + amount
            ), f"Incorrect balance for destination address `{addr}`"


class TestNotBalanced:
    @pytest.fixture(scope="class")
    def payment_addr(self, cluster_session):
        """Create 1 new payment address."""
        return create_payment_addrs("addr_not_balanced0", cluster_obj=cluster_session)[0]

    def test_negative_change(self, cluster_session, addrs_data_session, payment_addr, temp_dir):
        """Build a transaction with a negative change."""
        cluster = cluster_session
        src_address = addrs_data_session["user1"]["payment_addr"]
        dst_address = payment_addr.address

        tx_files = TxFiles(
            signing_key_files=[addrs_data_session["user1"]["payment_key_pair"].skey_file]
        )
        ttl = cluster.calculate_tx_ttl()

        fee = cluster.calculate_tx_fee(
            src_address, dst_addresses=[dst_address], tx_files=tx_files, ttl=ttl,
        )

        src_addr_highest_utxo = cluster.get_utxo_with_highest_amount(src_address)

        # use only the UTXO with highest amount
        txins = [
            TxIn(
                utxo_hash=src_addr_highest_utxo.utxo_hash,
                utxo_ix=src_addr_highest_utxo.utxo_ix,
                amount=src_addr_highest_utxo.amount,
            )
        ]
        # try to transfer +1 Lovelace more than available and use a negative change (-1)
        txouts = [
            TxOut(address=dst_address, amount=src_addr_highest_utxo.amount - fee + 1),
            TxOut(address=src_address, amount=-1),
        ]
        assert txins[0].amount - txouts[0].amount - fee == txouts[-1].amount

        with pytest.raises(CLIError) as excinfo:
            cluster.build_raw_tx_bare(
                out_file=temp_dir / "tx.body",
                txins=txins,
                txouts=txouts,
                tx_files=tx_files,
                fee=fee,
                ttl=ttl,
            )
        assert "option --tx-out: Failed reading" in str(excinfo.value)

    @pytest.mark.parametrize("amounts", [(1, 0), (-1, 2), (-5, 3)])
    def test_wrong_balance(
        self, cluster_session, addrs_data_session, payment_addr, temp_dir, amounts
    ):
        """Build a transaction with unbalanced change."""
        cluster = cluster_session
        src_address = addrs_data_session["user1"]["payment_addr"]
        dst_address = payment_addr.address

        out_file_tx = temp_dir / "tx.body"

        tx_files = TxFiles(
            signing_key_files=[addrs_data_session["user1"]["payment_key_pair"].skey_file]
        )
        ttl = cluster.calculate_tx_ttl()

        fee = cluster.calculate_tx_fee(
            src_address, dst_addresses=[dst_address], tx_files=tx_files, ttl=ttl,
        )

        src_addr_highest_utxo = cluster.get_utxo_with_highest_amount(src_address)

        # use only the UTXO with highest amount
        txins = [
            TxIn(
                utxo_hash=src_addr_highest_utxo.utxo_hash,
                utxo_ix=src_addr_highest_utxo.utxo_ix,
                amount=src_addr_highest_utxo.amount,
            )
        ]
        transfered_amount = src_addr_highest_utxo.amount - fee
        # Add to `transfered_amount` and change amount values from test's parameter.
        # Since correct change amount is 0, the value from test's parameter is used directly.
        transfer_add, change_amount = amounts
        txouts = [
            TxOut(address=dst_address, amount=transfered_amount + transfer_add),
            TxOut(address=src_address, amount=change_amount),
        ]

        # it should be possible to build and sign an unbalanced transaction
        cluster.build_raw_tx_bare(
            out_file=out_file_tx, txins=txins, txouts=txouts, tx_files=tx_files, fee=fee, ttl=ttl,
        )
        out_file_signed = cluster.sign_tx(
            tx_body_file=out_file_tx, signing_key_files=tx_files.signing_key_files,
        )

        # it should NOT be possible to submit an unbalanced transaction
        with pytest.raises(CLIError) as excinfo:
            cluster.submit_tx(tx_file=out_file_signed)
        assert "ValueNotConservedUTxO" in str(excinfo.value)


def test_negative_fee(cluster_session, addrs_data_session):
    """Send a transaction with negative fee (-1)."""
    cluster = cluster_session
    payment_addr = create_payment_addrs("addr_negative_fee0", cluster_obj=cluster_session)[0]
    src_address = addrs_data_session["user1"]["payment_addr"]

    tx_files = TxFiles(
        signing_key_files=[addrs_data_session["user1"]["payment_key_pair"].skey_file]
    )
    destinations = [TxOut(address=payment_addr.address, amount=10)]

    with pytest.raises(CLIError) as excinfo:
        cluster.send_funds(
            src_address=src_address, destinations=destinations, tx_files=tx_files, fee=-1,
        )
    assert "option --fee: cannot parse value" in str(excinfo.value)


def test_past_ttl(cluster_session, addrs_data_session):
    """Send a transaction with ttl in the past."""
    cluster = cluster_session
    payment_addr = create_payment_addrs("addr_past_ttl0", cluster_obj=cluster)[0]
    src_address = addrs_data_session["user1"]["payment_addr"]

    tx_files = TxFiles(
        signing_key_files=[addrs_data_session["user1"]["payment_key_pair"].skey_file]
    )
    destinations = [TxOut(address=payment_addr.address, amount=1)]
    ttl = cluster.get_last_block_slot_no() - 1
    fee = cluster.calculate_tx_fee(src_address, txouts=destinations, tx_files=tx_files, ttl=ttl)

    # it should be possible to build and sign a transaction with ttl in the past
    tx_raw_data = cluster.build_raw_tx(
        src_address=src_address, txouts=destinations, tx_files=tx_files, fee=fee, ttl=ttl,
    )
    out_file_signed = cluster.sign_tx(
        tx_body_file=tx_raw_data.out_file, signing_key_files=tx_files.signing_key_files,
    )

    # it should NOT be possible to submit a transaction with ttl in the past
    with pytest.raises(CLIError) as excinfo:
        cluster.submit_tx(tx_file=out_file_signed)
    assert "ExpiredUTxO" in str(excinfo.value)


def test_send_funds_to_reward_address(cluster_session, addrs_data_session, request):
    """Send funds from payment address to stake address."""
    cluster = cluster_session

    stake_addr = create_stake_addrs("addr_send_funds_to_reward_address0", cluster_obj=cluster)[0]
    payment_addr = create_payment_addrs(
        "addr_send_funds_to_reward_address0",
        cluster_obj=cluster,
        stake_vkey_file=stake_addr.vkey_file,
    )[0]

    # fund source address
    fund_from_faucet(
        payment_addr, cluster_obj=cluster, faucet_data=addrs_data_session["user1"], request=request,
    )

    tx_files = TxFiles(signing_key_files=[stake_addr.skey_file])
    destinations = [TxOut(address=stake_addr.address, amount=1000)]

    # it should NOT be possible to build a transaction using a stake address
    with pytest.raises(CLIError) as excinfo:
        cluster.build_raw_tx(
            src_address=payment_addr.address, txouts=destinations, tx_files=tx_files, fee=0,
        )
    assert "invalid address" in str(excinfo.value)
