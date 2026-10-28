# S15 model check (READINESS §1 S15 gate: the files load in GTAPv7-Julia and aggregations solve).
#
#   julia --project=s15_har/julia s15_har/julia/model_check.jl <output dir> <maps dir> <result file>
#
# 1. HeaderArrayFile reads gsdfset.har, gsdfpar.har and gsdfdat.har; every header is listed with its size.
# 2. The JLS copy (gtap_s15.jls.gz) holds the same sets and, for every array, values equal to the HAR values
#    within Float32 rounding.
# 3. The smoke map (maps/smoke_11x7_*.csv: 10 named regions plus the rest, 7 sectors, all 8 factors) is
#    aggregated with the package's aggregate_data, prepared in memory (prepare_for_solve.jl: an agent that buys
#    only one side of an Armington nest gets a tiny total- and tax-neutral share of the missing side; every
#    region must supply every margin, VST > 0, which S08 now guarantees), then the package's calibration sequence runs
#    (guide/public-database.md on main): generate_initial_model, generate_calibration_inputs, run_model!
#    on the calibration closure, rebuild_model!, and an unshocked run_model! on the default closure.
#    Pass: every solve ends solved and feasible (the check main's src/solve_model!.jl adds to 0.1.11), and the
#    unshocked solve moves no output quantity qo by more than 1e-6 relative. Then a +5% tariff power on mfr from
#    row to usa must solve, lower those imports and keep Walras' law (walras_sup = walras_dem within 1e-6).
# Each result is a line key=value in the result file; the last line is status=PASS or status=FAIL.
using HeaderArrayFile
using NamedArrays
using JuMP
using Serialization
using GlobalTradeAnalysisProjectModelV7
include(joinpath(@__DIR__, "prepare_for_solve.jl"))
# The package default is 50 Ipopt iterations; on the fix-round data the smoke map needs more to calibrate
# (it solves with 300; the S16 map suite uses the same 500 for its calibrations). The other solves keep the default.
const CALIBRATION_MAX_ITER = 500

const OUT, MAPS, RESULT = ARGS[1], ARGS[2], ARGS[3]
lines = String[]
ok = Ref(true)
note(k, v) = (push!(lines, "$k=$v"); println("$k=$v"))
fail(k, v) = (ok[] = false; note(k, v))

function load(path)
    har = HeaderArrayFile.File(path)
    return Dict(string(k) => v for (k, v) in zip(keys(har), values(har)))
end

setvec(x) = String.(strip.(String.(collect(HeaderArrayFile.data(HeaderArrayFile.data(x))))))

function readcsv(path)
    rows = [split(l, ",") for l in eachline(path)]
    return [String.(r) for r in rows[2:end]]
end

note("julia", VERSION)
note("package", "GlobalTradeAnalysisProjectModelV7 " * string(pkgversion(GlobalTradeAnalysisProjectModelV7)))

# ---------------------------------------------------------------- 1. load
raw = Dict{String,Dict{String,Any}}()
for f in ("set", "par", "dat")
    raw[f] = load(joinpath(OUT, "gsdf$(f).har"))
    for (k, v) in sort(collect(raw[f]); by = first)
        sz = k in ("drel", "reg", "comm", "acts", "endw", "marg", "endt") ? (length(setvec(v)),) : size(NamedArray(v))
        note("dims.$(f).$(k)", join(sz, "x"))
    end
end
sets = Dict(k => setvec(raw["set"][k]) for k in ("reg", "comm", "acts", "endw", "marg", "endt"))
hData = Dict(k => NamedArray(v) for (k, v) in raw["dat"] if k != "drel")
hParameters = Dict(k => NamedArray(v) for (k, v) in raw["par"] if k != "drel")
names(hData["vxsb"], 1) == sets["comm"] || fail("order.vxsb", "COMM axis differs from gsdfset")
names(hData["vxsb"], 2) == sets["reg"] || fail("order.vxsb", "REG axis differs from gsdfset")
names(hData["evfp"], 1) == sets["endw"] || fail("order.evfp", "ENDW axis differs from gsdfset")

# ---------------------------------------------------------------- 2. JLS against HAR
jls = open(`gzip -dc $(joinpath(OUT, "gtap_s15.jls.gz"))`) do io
    deserialize(io)
end
for k in keys(sets)
    jls["sets"][uppercase(k)] == sets[k] || fail("jls.sets.$k", "differs from gsdfset.har")
end
worst = 0.0
nj = 0
for (grp, har) in (("data", hData), ("parameters", hParameters))
    for (k, a) in jls[grp]
        k == "rdlt" && continue
        haskey(har, k) || (fail("jls.$k", "not in HAR"); continue)
        h = Array{Float64}(har[k])
        size(h) == size(a) || (fail("jls.$k", "size $(size(a)) vs HAR $(size(h))"); continue)
        g = maximum(abs.(h .- a) ./ max.(1.0, abs.(a)); init = 0.0)
        global worst = max(worst, g)
        global nj += 1
    end
    for k in keys(har)
        k in ("rdlt", "drel") && continue
        haskey(jls[grp], k) || fail("jls.$k", "HAR header not in the JLS")
    end
end
note("jls.arrays_compared", nj)
note("jls.max_rel_gap", worst)
worst <= 1.2e-7 || fail("jls.round_trip", "HAR differs from JLS beyond Float32 rounding")
Int(hParameters["rdlt"][1]) == jls["parameters"]["rdlt"] || fail("jls.rdlt", "differs")

# ---------------------------------------------------------------- 3. smoke map: aggregate, calibrate, solve
rrows = readcsv(joinpath(MAPS, "smoke_11x7_regions.csv"))
srows = readcsv(joinpath(MAPS, "smoke_11x7_sectors.csv"))
rgrp = Dict(String(lowercase(r[1])) => String(r[2]) for r in rrows if r[1] != "*")
rest = String(only([r[2] for r in rrows if r[1] == "*"]))
sgrp = Dict(String(lowercase(r[1])) => String(r[2]) for r in srows)
all(c -> haskey(sgrp, c), sets["comm"]) || fail("map.sectors", "a sector has no group")
regMap = NamedArray([get(rgrp, r, rest) for r in sets["reg"]], sets["reg"])
comMap = NamedArray([sgrp[c] for c in sets["comm"]], sets["comm"])
endMap = NamedArray(copy(sets["endw"]), sets["endw"])
hSets = Dict("reg" => sets["reg"], "comm" => sets["comm"], "acts" => sets["acts"], "marg" => sets["marg"], "endw" => sets["endw"])
t0 = time()

function solved(mc, step)
    st = termination_status(mc.model)
    note("smoke.$(step).termination", st)
    is_solved_and_feasible(mc.model) || fail("smoke.$(step)", "not solved and feasible ($st)")
end

try
    agg = aggregate_data(; hData = hData, hParameters = hParameters, hSets = hSets, comMap, regMap, endMap)
    note("smoke.regions", join(agg.hSets["reg"], " "))
    note("smoke.comm", join(agg.hSets["comm"], " "))
    note("smoke.marg", join(agg.hSets["marg"], " "))
    n, v = armington_swap!(agg.hData)
    note("smoke.prep.armington_cells", n)
    note("smoke.prep.armington_moved", round(v; sigdigits = 6))
    minvst = minimum(Array{Float64}(agg.hData["vst"]))
    note("smoke.min_vst", round(minvst; sigdigits = 6))
    minvst > 0 || fail("smoke.vst", "a region supplies no margin (VST = 0); the model takes log(qst)")
    mc = generate_initial_model(; hSets = agg.hSets, hData = agg.hData, hParameters = agg.hParameters)
    start_data = deepcopy(mc.data)
    (; fixed_calibration, data_calibration) = generate_calibration_inputs(mc, start_data)
    fixed_default = deepcopy(mc.fixed)
    mc.data = data_calibration
    mc.fixed = fixed_calibration
    run_model!(mc; max_iter = CALIBRATION_MAX_ITER)
    solved(mc, "calibration")
    calibrated_data = deepcopy(mc.data)
    rebuild_model!(mc)
    mc.fixed = deepcopy(fixed_default)
    mc.data = deepcopy(calibrated_data)
    run_model!(mc)
    solved(mc, "unshocked")
    q0 = Array{Float64}(calibrated_data["qo"])
    q1 = Array{Float64}(mc.data["qo"])
    mv = maximum(abs.(q1 .- q0) ./ max.(1e-12, abs.(q0)); init = 0.0)
    note("smoke.unshocked_max_rel_move_qo", mv)
    mv <= 1e-6 || fail("smoke.unshocked", "output moved by $mv")
    # A small shock shows the model responds and keeps Walras' law: +5% import tariff power on mfr from row to usa.
    unshocked = deepcopy(mc.data)
    mc.data["tms"]["mfr", "row", "usa"] *= 1.05
    run_model!(mc)
    solved(mc, "tariff_shock")
    dq = mc.data["qxs"]["mfr", "row", "usa"] / unshocked["qxs"]["mfr", "row", "usa"] - 1
    note("smoke.tariff_shock_qxs_mfr_row_usa_pct", round(100 * dq; digits = 4))
    dq < 0 || fail("smoke.tariff_shock", "imports of mfr from row to usa did not fall ($dq)")
    ws, wd = Float64(first(mc.data["walras_sup"])), Float64(first(mc.data["walras_dem"]))
    note("smoke.tariff_shock_walras_gap", round(abs(ws - wd) / abs(wd); sigdigits = 3))
    abs(ws - wd) <= 1e-6 * abs(wd) || fail("smoke.tariff_shock", "Walras gap $(abs(ws - wd))")
catch e
    fail("smoke.error", replace(sprint(showerror, e), '\n' => ' ')[1:min(end, 400)])
end
println("smoke.seconds=", round(time() - t0; digits = 1))   # log only, so the result file is the same on two runs
note("status", ok[] ? "PASS" : "FAIL")
open(RESULT, "w") do io
    foreach(l -> println(io, l), lines)
end
exit(ok[] ? 0 : 1)
