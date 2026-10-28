# S16 map suite (PLAN §4 items 1-3; READINESS §1 S16): every aggregation map is aggregated from the finished
# data base, prepared, calibrated and solved in GlobalTradeAnalysisProjectModelV7.
#
#   julia --project=s15_har/julia s16_final/julia/map_suite.jl <S15 output dir> <map dir> <result file> [map ...]
#
# <map dir> holds the resolved maps the S16 stage writes: maps_list.csv (map, tariff_shock), maps_regions.csv
# (map, region, group) and maps_sectors.csv (map, sector, group). Factors are not aggregated (all eight kept).
# With map names after the result file, only those maps run (the stage splits the suite over a few processes).
#
# For each map:
#   1. aggregate_data, the zero-weight parameter fallback and the S15 in-memory Armington preparation (s15_har/julia/prepare_for_solve.jl);
#      VST > 0 is asserted.
#   2. Calibration closure, then the unshocked default closure: both solved and feasible; qo moves <= 1e-6.
#   3. Homogeneity (PLAN §4 item 1): every nominal variable x 1.1 (the numeraire with them), default closure.
#      Every model variable is classified (NOMINAL, REAL, PARAM below; an unclassified one stops the map).
#      Pass: solved and feasible; every nominal variable moves by x 1.1 and every real one by 0, within 1e-6,
#      except psave and qsave. Those two are reported against the package's own e_psave, which is
#      log(psave_r) = log(pinv_r) + sum_s w_s log(pinv_s), w_s = (qinv_s - δ_s kb_s - qsave_s) / sum(qinv - δ kb).
#      The equation is homogeneous of degree 1 only if sum w = 0, i.e. world qsave equals world net investment in
#      model quantities; the package values investment at basic prices in walras_sup (S14-Rinvbasic), so sum w is
#      not zero and psave moves off x 1.1 (S15 QA N7). The check: psave equals the move predicted from the unshocked
#      values and e_psave alone (fixed point below) within 1e-6, so the quirk is the package's, not the data base's.
#   4. Where maps_list names a tariff shock (comm, src, dst), +10% on tms (PLAN §4): solved, qxs falls, Walras gap <= 1e-6.
# Each result is a line "<map>.<key>=<value>"; "<map>.status=PASS|FAIL" closes each map.
using HeaderArrayFile
using NamedArrays
using JuMP
using GlobalTradeAnalysisProjectModelV7
include(joinpath(@__DIR__, "..", "..", "s15_har", "julia", "prepare_for_solve.jl"))

const OUT, MAPDIR, RESULT = ARGS[1], ARGS[2], ARGS[3]
const ONLY = Set(ARGS[4:end])
# Every variable of build_model!.jl (default closure), classified for the homogeneity test. A model variable in none
# of the three sets stops the map, so a package update cannot slip a variable past the test.
const NOMINAL = Set(["fincome", "p", "pca", "pcgdswld", "pcif", "pds", "pe", "peb", "pes", "pfa", "pfactor", "pfactwld", "pfd",
    "pfe", "pfm", "pfob", "pga", "pgd", "pgm", "pgov", "pia", "pid", "pim", "pint", "pinv", "pmds", "pms", "po", "ppa", "ppd",
    "ppm", "ppriv", "ps", "psave", "pt", "ptrans", "pva", "rental", "walras_dem", "walras_sup", "y", "yg", "yp"])
const REAL = Set(["globalcgds", "kb", "ke", "qc", "qca", "qds", "qe", "qes", "qesf", "qfa", "qfd", "qfe", "qfm", "qga", "qgd",
    "qgm", "qia", "qid", "qim", "qint", "qinv", "qms", "qo", "qpa", "qpd", "qpm", "qsave", "qst", "qtm", "qtmfsd", "qva", "qxs",
    "rorc", "rore", "rorg", "u", "uelas", "uepriv", "ug", "up", "pop"])           # quantities, rates of return, utility, elasticities
const PARAM = Set(["tfd", "tfe", "tfm", "tgd", "tgm", "tid", "tim", "tinc", "tm", "tms", "to", "tpd", "tpm", "tx", "txs", "σyg", "σyp"])
const QUIRK = Set(["psave", "qsave", "p", "u"])        # psave, and what e_p and e_u carry of it (tested below)
# The package default is 50 Ipopt iterations; the saving-tails closure map (aggregation_B) needs more to calibrate.
const CALIBRATION_MAX_ITER = 3000   # final round 2026-10-25: aggregation_B (both saving tails) stopped at 500
const FACTOR = 1.1

# Solver backend (final round 2026-10-25, David): ZeroHessAD gives JuMP an evaluator whose Hessian is identically zero.
# The model is square, so Ipopt's Newton step does not use the Hessian; skipping the AD Hessian build makes each iteration
# about 30x faster and lets large maps fit in memory, with the same iterations and results as the package default
# (solve benchmark, qa/solve_benchmark). S16_SOLVER=exact restores the default.
const SOLVER = get(ENV, "S16_SOLVER", "zerohess")
SOLVER in ("zerohess", "exact") || error("S16_SOLVER must be zerohess or exact, not $SOLVER")
const NL = MOI.Nonlinear
struct ZeroHessAD <: NL.AbstractAutomaticDifferentiation end
struct ZeroHessEval <: MOI.AbstractNLPEvaluator
    inner::MOI.AbstractNLPEvaluator
end
NL.Evaluator(model::NL.Model, ::ZeroHessAD, vars::Vector{MOI.VariableIndex}) =
    NL.Evaluator(model, ZeroHessEval(NL.Evaluator(model, NL.SparseReverseMode(), vars).backend))
MOI.features_available(::ZeroHessEval) = [:Grad, :Jac, :Hess]
MOI.initialize(e::ZeroHessEval, f::Vector{Symbol}) = MOI.initialize(e.inner, filter(!=(:Hess), f))
MOI.hessian_lagrangian_structure(::ZeroHessEval) = Tuple{Int64,Int64}[]
MOI.eval_hessian_lagrangian(::ZeroHessEval, H, x, σ, μ) = nothing
for fn in (:eval_objective, :eval_objective_gradient, :eval_constraint, :eval_constraint_jacobian, :jacobian_structure,
           :eval_constraint_jacobian_product, :eval_constraint_jacobian_transpose_product)
    @eval MOI.$fn(e::ZeroHessEval, args...) = MOI.$fn(e.inner, args...)
end
function setopts!(model)
    set_attribute(model, "print_level", 0)
    SOLVER == "zerohess" && set_attribute(model, MOI.AutomaticDifferentiationBackend(), ZeroHessAD())
end

lines = String[]
note(m, k, v) = (push!(lines, "$m.$k=$v"); println("$m.$k=$v"); flush(stdout))

function load(path)
    har = HeaderArrayFile.File(path)
    return Dict(string(k) => v for (k, v) in zip(keys(har), values(har)))
end
setvec(x) = String.(strip.(String.(collect(HeaderArrayFile.data(HeaderArrayFile.data(x))))))
readcsv(path) = [String.(split(l, ",")) for l in collect(eachline(path))[2:end]]

raw = Dict(f => load(joinpath(OUT, "gsdf$(f).har")) for f in ("set", "par", "dat"))
sets = Dict(k => setvec(raw["set"][k]) for k in ("reg", "comm", "acts", "endw", "marg"))
hData0 = Dict(k => NamedArray(v) for (k, v) in raw["dat"] if k != "drel")
hPar0 = Dict(k => NamedArray(v) for (k, v) in raw["par"] if k != "drel")
hSets0 = Dict("reg" => sets["reg"], "comm" => sets["comm"], "acts" => sets["acts"], "marg" => sets["marg"], "endw" => sets["endw"])

maps = readcsv(joinpath(MAPDIR, "maps_list.csv"))
rrows = readcsv(joinpath(MAPDIR, "maps_regions.csv"))
srows = readcsv(joinpath(MAPDIR, "maps_sectors.csv"))

arr(x) = x isa Number ? [Float64(x)] : vec(Float64.(Array(x)))
function relmove(a, b, factor)
    x, y = arr(a), arr(b)
    keep = abs.(y) .> 1e-12
    any(keep) || return 0.0
    return maximum(abs.(x[keep] ./ (factor .* y[keep]) .- 1))
end

function ok_solve(m, mc, step)
    st = termination_status(mc.model)
    note(m, "$(step).termination", st)
    is_solved_and_feasible(mc.model) || error("$step not solved and feasible ($st)")
end

function run_map(m, shock)
    rg = Dict(lowercase(r[2]) => r[3] for r in rrows if r[1] == m)
    sg = Dict(lowercase(r[2]) => r[3] for r in srows if r[1] == m)
    all(r -> haskey(rg, r), sets["reg"]) || error("a region has no group on this map")
    all(c -> haskey(sg, c), sets["comm"]) || error("a sector has no group on this map")
    regMap = NamedArray([rg[r] for r in sets["reg"]], sets["reg"])
    comMap = NamedArray([sg[c] for c in sets["comm"]], sets["comm"])
    endMap = NamedArray(copy(sets["endw"]), sets["endw"])
    agg = aggregate_data(; hData = deepcopy(hData0), hParameters = deepcopy(hPar0), hSets = hSets0, comMap, regMap, endMap)
    zw = fill_zero_weight_parameters!(agg.hParameters, hPar0, [comMap, regMap, endMap])
    note(m, "prep.zero_weight_parameters", length(zw))
    isempty(zw) || note(m, "prep.zero_weight_cells", join(unique(["$(k)[$(join(g, ' '))]" for (k, g, _) in zw]), "; "))
    note(m, "regions", join(agg.hSets["reg"], " "))
    note(m, "comm", join(agg.hSets["comm"], " "))
    n, v = armington_swap!(agg.hData)
    note(m, "prep.armington_cells", n)
    note(m, "prep.armington_moved", round(v; sigdigits = 6))
    minvst = minimum(Array{Float64}(agg.hData["vst"]))
    note(m, "min_vst", round(minvst; sigdigits = 6))
    minvst > 0 || error("a region supplies no margin (VST = 0)")

    mc = generate_initial_model(; hSets = agg.hSets, hData = agg.hData, hParameters = agg.hParameters)
    setopts!(mc.model)
    note(m, "solver", SOLVER)
    (; fixed_calibration, data_calibration) = generate_calibration_inputs(mc, deepcopy(mc.data))
    fixed_default = deepcopy(mc.fixed)
    mc.data = data_calibration
    mc.fixed = fixed_calibration
    run_model!(mc; max_iter = CALIBRATION_MAX_ITER)
    ok_solve(m, mc, "calibration")
    calibrated = deepcopy(mc.data)
    note(m, "sigma_save_min", round(minimum(arr(calibrated["σsave"])); digits = 6))
    note(m, "sigma_save_max", round(maximum(arr(calibrated["σsave"])); digits = 6))
    rebuild_model!(mc)
    setopts!(mc.model)
    mc.fixed = deepcopy(fixed_default)
    mc.data = deepcopy(calibrated)
    run_model!(mc)
    ok_solve(m, mc, "unshocked")
    mv = relmove(mc.data["qo"], calibrated["qo"], 1.0)
    note(m, "unshocked_max_rel_move_qo", mv)
    mv <= 1e-6 || error("unshocked solve moved output by $mv")
    base = deepcopy(mc.data)
    wg = abs(Float64(first(base["walras_sup"])) - Float64(first(base["walras_dem"]))) / abs(Float64(first(base["walras_dem"])))
    note(m, "unshocked_walras_gap", round(wg; sigdigits = 3))

    # homogeneity: every nominal variable x 1.1 (the fixed numeraire with them; the others as starting values), default closure
    objs = JuMP.object_dictionary(mc.model)
    isvar(v) = v isa VariableRef || (v isa AbstractArray && !isempty(v) && first(v) isa VariableRef)
    mvars = sort([String(k) for (k, v) in objs if isvar(v)])
    unknown = setdiff(mvars, NOMINAL ∪ REAL ∪ PARAM ∪ keys(fixed_default))
    isempty(unknown) || error("homogeneity: model variables not classified: $(join(unknown, ' '))")
    tested = [k for k in mvars if (k in NOMINAL || k in REAL) && haskey(base, k)]
    note(m, "homogeneity_variables_tested", length(tested))
    mc.data = deepcopy(base)
    for k in tested
        k in NOMINAL || continue
        mc.data[k] isa Number ? (mc.data[k] *= FACTOR) : (mc.data[k] .*= FACTOR)
    end
    mc.fixed = deepcopy(fixed_default)
    run_model!(mc)
    ok_solve(m, mc, "homogeneity")
    pw, qw, pwk, qwk = 0.0, 0.0, "", ""
    for k in tested
        k in QUIRK && continue
        g = relmove(mc.data[k], base[k], k in NOMINAL ? FACTOR : 1.0)
        if k in NOMINAL
            g > pw && ((pw, pwk) = (g, k))
        else
            g > qw && ((qw, qwk) = (g, k))
        end
    end
    note(m, "homogeneity_max_price_gap", pw)
    note(m, "homogeneity_max_price_gap_variable", pwk)
    note(m, "homogeneity_max_quantity_gap", qw)
    note(m, "homogeneity_max_quantity_gap_variable", qwk)
    # psave under the package's e_psave, from the unshocked values alone: if every other variable scales exactly,
    # psave_r moves by ρ and qsave by 1.1/ρ (e_qsave), so log ρ = log 1.1 + Σ_s w_s(ρ)(log pinv_s + log 1.1) - Σ_s w_s log pinv_s,
    # with w_s(ρ) = (netinv_s - qsave_s 1.1/ρ) / Σ netinv. Solved by fixed-point iteration.
    netinv = arr(base["qinv"]) .- arr(base["δ"]) .* arr(base["kb"])
    qs, lp = arr(base["qsave"]), log.(arr(base["pinv"]))
    sw = (sum(netinv) - sum(qs)) / sum(netinv)
    # where Σw comes from: the data (Σ SAVE = Σ(I - VDEP) at purchasers' prices) against the calibrated base
    note(m, "psave_data_sum_save", sum(arr(agg.hData["save"])))
    note(m, "psave_data_sum_netinv", sum(arr(agg.hData["vdip"])) + sum(arr(agg.hData["vmip"])) - sum(arr(agg.hData["vdep"])))
    note(m, "psave_base_sum_qsave", sum(qs))
    note(m, "psave_base_sum_qinv", sum(arr(base["qinv"])))
    note(m, "psave_base_sum_depreciation", sum(arr(base["δ"]) .* arr(base["kb"])))
    # Walras balances values (Σ psave qsave = pcgdswld Σ netinv), so Σw = (Σ netinv - Σ qsave) / Σ netinv in quantities is
    # zero only when psave is the same in every region
    note(m, "psave_base_min", minimum(arr(base["psave"])))
    note(m, "psave_base_max", maximum(arr(base["psave"])))
    note(m, "psave_base_value_gap", abs(sum(arr(base["psave"]) .* qs) - first(arr(base["pcgdswld"])) * sum(netinv)) / sum(netinv))
    w0 = (netinv .- qs) ./ sum(netinv)
    ρ = FACTOR
    for _ in 1:200
        w = (netinv .- qs .* FACTOR ./ ρ) ./ sum(netinv)
        ρ = exp(log(FACTOR) + sum(w .* (lp .+ log(FACTOR))) - sum(w0 .* lp))
    end
    pred = ρ
    obs = arr(mc.data["psave"]) ./ arr(base["psave"])
    qobs = arr(mc.data["qsave"]) ./ arr(base["qsave"])
    note(m, "homogeneity_psave_sum_w", sw)
    note(m, "homogeneity_psave_ratio_min", minimum(obs))
    note(m, "homogeneity_psave_ratio_max", maximum(obs))
    note(m, "homogeneity_psave_ratio_predicted", pred)
    pg = maximum(abs.(obs ./ pred .- 1))
    qg = maximum(abs.(qobs ./ (FACTOR / pred) .- 1))
    note(m, "homogeneity_psave_gap_to_prediction", pg)
    note(m, "homogeneity_qsave_gap_to_prediction", qg)
    # e_p: p = ppriv σyp + pgov σyg + psave (1 - σyp - σyg), so p carries psave's share of the quirk, and u = y / p / pop
    sp, sg = arr(base["σyp"]), arr(base["σyg"])
    ppred = (FACTOR .* (arr(base["ppriv"]) .* sp .+ arr(base["pgov"]) .* sg) .+ pred .* arr(base["psave"]) .* (1 .- sp .- sg)) ./ arr(base["p"])
    pug = max(maximum(abs.(arr(mc.data["p"]) ./ arr(base["p"]) ./ ppred .- 1)),
              maximum(abs.(arr(mc.data["u"]) ./ arr(base["u"]) ./ (FACTOR ./ ppred) .- 1)))
    note(m, "homogeneity_p_u_gap_to_prediction", pug)
    pw <= 1e-6 || error("homogeneity: $pwk moved off x$FACTOR by $pw")
    pug <= 1e-6 || error("homogeneity: p or u is off the e_p prediction by $pug")
    qw <= 1e-6 || error("homogeneity: $qwk moved by $qw")
    pg <= 1e-6 || error("homogeneity: psave is off the package's own e_psave prediction by $pg")
    qg <= 1e-6 || error("homogeneity: qsave is off 1.1/psave move by $qg")

    if !isempty(shock)
        c, s, d = split(shock, ":")
        mc.data = deepcopy(base)
        mc.fixed = deepcopy(fixed_default)
        mc.data["tms"][c, s, d] *= 1.10
        run_model!(mc)
        ok_solve(m, mc, "tariff_shock")
        dq = mc.data["qxs"][c, s, d] / base["qxs"][c, s, d] - 1
        note(m, "tariff_shock_qxs_pct", round(100 * dq; digits = 4))
        dq < 0 || error("tariff shock: imports did not fall ($dq)")
        ws, wd = Float64(first(mc.data["walras_sup"])), Float64(first(mc.data["walras_dem"]))
        note(m, "tariff_shock_walras_gap", round(abs(ws - wd) / abs(wd); sigdigits = 3))
        abs(ws - wd) <= 1e-6 * abs(wd) || error("tariff shock: Walras gap $(abs(ws - wd))")
    end
end

for row in maps
    m, shock = row[1], length(row) > 1 ? row[2] : ""
    isempty(ONLY) || m in ONLY || continue
    t0 = time()
    ok = try
        run_map(m, shock)
        true
    catch e
        note(m, "error", replace(sprint(showerror, e), '\n' => ' ', ',' => ';')[1:min(end, 400)])
        false
    end
    println("$m.seconds=", round(time() - t0; digits = 1))   # log only
    note(m, "status", ok ? "PASS" : "FAIL")
    open(RESULT, "w") do io
        foreach(l -> println(io, l), lines)
    end
end
