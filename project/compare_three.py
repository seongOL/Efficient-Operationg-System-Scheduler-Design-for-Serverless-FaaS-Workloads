import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

IN_FILES = {
    "CFS": "./CFS/CFS_result.csv",
    "FIFO": "./FIFO/FIFO_result.csv",
    "CUSTOM": "./CUSTOM/CUSTOM_result.csv",
}
OUT_DIR = "./compare_results/three"
os.makedirs(OUT_DIR, exist_ok=True)

def read_df(path):
    if not os.path.exists(path):
        print(f"[WARN] not found: {path}")
        return pd.DataFrame()
    return pd.read_csv(path)

def to_num(col):
    return pd.to_numeric(col, errors="coerce").dropna().to_numpy(dtype=float)

def avg(a):  return float(np.mean(a)) if len(a) else 0.0
def pct(a,p): return float(np.percentile(a,p)) if len(a) else 0.0

def ecdf(a):
    if len(a)==0: return np.array([]),np.array([])
    x=np.sort(a)
    y=np.arange(1,len(x)+1)/len(x)
    x=np.insert(x,0,0.0); y=np.insert(y,0,0.0)
    return x,y

def plot_ecdf(name, xlabel, series_dict, xlim=None):
    plt.figure(figsize=(6,4),dpi=150)
    for label,arr in series_dict.items():
        x,y=ecdf(arr)
        if len(x): plt.plot(x,y,label=label,linewidth=2)
    plt.xlabel(xlabel)
    plt.ylabel("Cumulative probability")
    plt.ylim(0,1)
    if xlim: plt.xlim(xlim)
    plt.grid(alpha=0.3)
    plt.legend()
    plt.tight_layout()
    out=os.path.join(OUT_DIR,f"{name}.png")
    plt.savefig(out)
    plt.close()
    return out

def make_stats(series):
    return {
        "Turnaround":{"avg":avg(series["Turnaround"]),"p95":pct(series["Turnaround"],95),"p99":pct(series["Turnaround"],99)},
        "Execution":{"avg":avg(series["Execution"]),"p95":pct(series["Execution"],95),"p99":pct(series["Execution"],99)},
        "Response":{"avg":avg(series["Response"]),"p95":pct(series["Response"],95),"p99":pct(series["Response"],99)},
        "CtxΔ":{"avg":avg(series["CtxΔ"]),"p95":pct(series["CtxΔ"],95),"p99":pct(series["CtxΔ"],99)},
    }

def save_summary_table(stats):
    rows=[]; scheds=["CFS","FIFO","CUSTOM"]
    order=[("Turnaround",["avg","p95","p99"]),
           ("Execution",["avg","p95","p99"]),
           ("Response",["avg","p95","p99"]),
           ("CtxΔ",["avg","p95","p99"])]
    data={s:[] for s in scheds}
    for m,keys in order:
        for k in keys:
            rows.append(f"{m} {k}")
            for s in scheds:
                data[s].append(stats[s][m][k])
    df=pd.DataFrame(data,index=rows)

    fig,ax=plt.subplots(figsize=(6.8,0.4*len(df.index)+1.5),dpi=150)
    ax.axis("off")
    df_fmt=df.applymap(lambda v:f"{v:.2f}")
    tb=ax.table(cellText=df_fmt.values,rowLabels=df_fmt.index,
                colLabels=df_fmt.columns,loc='center',cellLoc='center')
    tb.auto_set_font_size(False)
    tb.set_fontsize(9)
    tb.scale(1.05,1.15)
    plt.tight_layout()
    out=os.path.join(OUT_DIR,"summary_table.png")
    plt.savefig(out,bbox_inches="tight")
    plt.close()
    return out

def main():
    dfs={k:read_df(p) for k,p in IN_FILES.items()}
    series={}
    for k,df in dfs.items():
        series[k]={
            "Turnaround":to_num(df.get("trun_around_ms",[])),
            "Execution":to_num(df.get("exec_ms",[])),
            "Response":to_num(df.get("res_ms",[])),
            "CtxΔ":to_num(df.get("ctxsw_delta_total",[]))
        }

    paths=[]
    paths.append(plot_ecdf("execution","Execution (ms)",
                {"CFS":series["CFS"]["Execution"],"FIFO":series["FIFO"]["Execution"],"CUSTOM":series["CUSTOM"]["Execution"]}))
    paths.append(plot_ecdf("response","Response (ms)",
                {"CFS":series["CFS"]["Response"],"FIFO":series["FIFO"]["Response"],"CUSTOM":series["CUSTOM"]["Response"]},
                xlim=(0,500)))
    paths.append(plot_ecdf("turnaround","Turnaround (ms)",
                {"CFS":series["CFS"]["Turnaround"],"FIFO":series["FIFO"]["Turnaround"],"CUSTOM":series["CUSTOM"]["Turnaround"]},
                xlim=(0,600)))
    paths.append(plot_ecdf("ctxswitch","Context Switch Δ (count)",
                {"CFS":series["CFS"]["CtxΔ"],"FIFO":series["FIFO"]["CtxΔ"],"CUSTOM":series["CUSTOM"]["CtxΔ"]},
                xlim=(0,150)))

    stats={k:make_stats(series[k]) for k in ["CFS","FIFO","CUSTOM"]}
    paths.append(save_summary_table(stats))

    print("\n[Saved Outputs]")
    for p in paths: print(" -",p)

if __name__=="__main__":
    main()

