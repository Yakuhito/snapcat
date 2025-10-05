from typing import Dict, List, Tuple, Union
from chia.types.blockchain_format.coin import Coin
from chia_rs.sized_bytes import bytes32
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.consensus.condition_tools import conditions_dict_for_solution
from chia_rs.sized_ints import uint64
from clvm.casts import int_from_bytes

from chia.wallet.cat_wallet.cat_utils import match_cat_puzzle
from chia.wallet.vc_wallet.vc_drivers import match_revocation_layer
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.cat_wallet.cat_utils import CAT_MOD_HASH


def created_outputs_for_conditions_dict(
    conditions_dict: Dict[ConditionOpcode, List[ConditionWithArgs]],
    input_coin_name: bytes32,
) -> List[Coin]:
    output_coins = []
    for cvp in conditions_dict.get(ConditionOpcode.CREATE_COIN, []):
        puzzle_hash, amount_bin = cvp.vars[0], cvp.vars[1]
        amount = int_from_bytes(amount_bin)
        # ignore magic conditions
        if amount > 0:
            coin = Coin(input_coin_name, bytes32(puzzle_hash), uint64(amount))
            output_coins.append(coin)
    return output_coins


def extract_cat(
    expected_tail_hash: bytes32,
    hidden_puzzle_hash: bytes32 | None,
    coin_spend: CoinSpend,
) -> Union[None, Tuple[Program, Program, Program, Program, Program]]:
    outer_puzzle = coin_spend.puzzle_reveal
    outer_solution = Program.from_bytes(coin_spend.solution.to_bytes())
    cat_curried_args = match_cat_puzzle(uncurry_puzzle(outer_puzzle))
    if cat_curried_args is None:
        return None

    cat_curried_args = list(cat_curried_args)
    if len(cat_curried_args) != 3:
        return None

    # CAT2
    cat_mod_hash, tail_program_hash, inner_puzzle = cat_curried_args
    tail_hash = bytes32(tail_program_hash.as_atom())
    cat_mod_hash = bytes32(cat_mod_hash.as_atom())
    if tail_hash != expected_tail_hash or cat_mod_hash != CAT_MOD_HASH:
        return None

    inner_solution = None
    if hidden_puzzle_hash is None:
        inner_solution = outer_solution.first()
    else:
        revocation_layer_curried_args = match_revocation_layer(uncurry_puzzle(inner_puzzle))
        if revocation_layer_curried_args is None:
            return None

        revocation_layer_curried_args = list(revocation_layer_curried_args)
        if len(revocation_layer_curried_args) != 2:
            return None
        
        hidden_puzzle_hash_arg, inner_puzzle_hash = revocation_layer_curried_args
        if hidden_puzzle_hash_arg != hidden_puzzle_hash:
            return None
        
        interim_solution = outer_solution.first()
        hidden = bool(interim_solution.first().as_atom())
        inner_puzzle = interim_solution.rest().first()
        actual_inner_puzzle_hash = inner_puzzle.get_tree_hash()
        inner_solution = interim_solution.rest().rest().first()

        if (hidden and actual_inner_puzzle_hash != hidden_puzzle_hash) or (not hidden and actual_inner_puzzle_hash != inner_puzzle_hash):
            return None

    return tail_hash, outer_puzzle, outer_solution, inner_puzzle, inner_solution


def create_coin_conditions_for_inner_puzzle(
    coin_spend_name: bytes32, inner_puzzle: Program, inner_solution: Program
):
    inner_puzzle_conditions = conditions_dict_for_solution(
        inner_puzzle, inner_solution, 0
    )

    inner_puzzle_create_coin_conditions = []
    if inner_puzzle_conditions is not None:
        inner_puzzle_create_coin_conditions = created_outputs_for_conditions_dict(
            inner_puzzle_conditions, coin_spend_name
        )

    return inner_puzzle_create_coin_conditions
