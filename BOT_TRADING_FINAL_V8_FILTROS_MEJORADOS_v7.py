# BOT_TRADING_FINAL_V8_FILTROS_MEJORADOS_CORREGIDO.py

import tkinter as tk
from tkinter import ttk
import threading
import datetime
import time
import json
import websocket
import numpy as np
import csv

class DerivAPI:
    def __init__(self, token):
        self.token = token
        self.ws = None
        self.account_type = "DESCONOCIDO"
        self.balance = 0.0
        self.account_id = ""

    def connect(self):
        try:
            self.ws = websocket.create_connection("wss://ws.binaryws.com/websockets/v3?app_id=1089")
            self.ws.send(json.dumps({"authorize": self.token}))
            auth = json.loads(self.ws.recv())
            if "error" in auth:
                return False, auth["error"]["message"]
            acc_id = auth["authorize"]["loginid"]
            self.account_id = acc_id
            self.account_type = "DEMO" if "VRTC" in acc_id else "REAL"
            self.ws.send(json.dumps({"balance": 1}))
            balance_data = json.loads(self.ws.recv())
            self.balance = balance_data.get("balance", {}).get("balance", 0)
            return True, f"Cuenta: {self.account_type} ({acc_id}) | Saldo: ${self.balance:.2f}"
        except Exception as e:
            return False, str(e)

    def get_ticks(self, symbol, count=100):
        self.ws.send(json.dumps({
            "ticks_history": symbol,
            "count": count,
            "end": "latest",
            "style": "ticks"
        }))
        data = json.loads(self.ws.recv())
        return [float(p) for p in data["history"]["prices"]] if "history" in data else []

    def buy_contract(self, symbol, contract_type, duration, duration_unit, amount):
        self.ws.send(json.dumps({
            "proposal": 1,
            "amount": amount,
            "basis": "stake",
            "contract_type": contract_type,
            "currency": "USD",
            "duration": duration,
            "duration_unit": duration_unit,
            "symbol": symbol
        }))
        proposal = json.loads(self.ws.recv())
        if "error" in proposal or "proposal" not in proposal:
            return None, proposal.get("error", {}).get("message", "Error al obtener propuesta")

        proposal_id = proposal["proposal"]["id"]
        self.ws.send(json.dumps({"buy": proposal_id, "price": proposal["proposal"]["ask_price"]}))
        response = json.loads(self.ws.recv())

        if "buy" not in response:
            return None, response.get("error", {}).get("message", "Error al ejecutar compra")

        return response["buy"]["contract_id"], None

    def check_result(self, contract_id):
        try:
            while True:
                self.ws.send(json.dumps({"proposal_open_contract": 1, "contract_id": contract_id}))
                result = json.loads(self.ws.recv())
                if "proposal_open_contract" in result and result["proposal_open_contract"]["is_sold"]:
                    return float(result["proposal_open_contract"]["profit"])
                time.sleep(1)
        except websocket.WebSocketConnectionClosedException:
            return 0.0

    def close(self):
        if self.ws:
            self.ws.close()

class TradingBot:
    def __init__(self, root):
        self.root = root
        self.token = tk.StringVar()
        self.symbol = tk.StringVar(value="R_50")
        self.stake = tk.DoubleVar(value=1.0)
        self.duration = tk.IntVar(value=60)
        self.martingala = tk.DoubleVar(value=2.0)
        self.contract_type = tk.StringVar(value="AMBOS")
        self.duration_mode = tk.StringVar(value="s")
        self.profit_target = tk.DoubleVar(value=10.0)
        self.stop_loss = tk.DoubleVar(value=-10.0)
        self.rsi_filter = tk.BooleanVar()
        self.ema_filter = tk.BooleanVar()
        self.cci_filter = tk.BooleanVar()
        self.engulf_filter = tk.BooleanVar()
        self.all_filters = tk.BooleanVar()

        self.rsi_min = tk.DoubleVar(value=40)
        self.rsi_max = tk.DoubleVar(value=60)
        self.cci_threshold = tk.DoubleVar(value=200)
        self.ema_fast = tk.IntVar(value=5)
        self.ema_slow = tk.IntVar(value=20)
        self.engulf_mode = tk.StringVar(value="standard")

        self.operating = False
        self.api = None
        self.ganadas = 0
        self.perdidas = 0
        self.neto = 0.0
        self.build_gui()

    def build_gui(self):
        frame = tk.Frame(self.root)
        frame.pack()

        # Parámetros estándar
        tk.Label(frame, text="Token").grid(row=0, column=0)
        tk.Entry(frame, textvariable=self.token, width=35).grid(row=0, column=1)
        tk.Button(frame, text="Conectar", command=self.connect).grid(row=0, column=2)
        tk.Button(frame, text="Desconectar", command=self.disconnect).grid(row=0, column=3)
        tk.Label(frame, text="Símbolo").grid(row=1, column=0)
        tk.Entry(frame, textvariable=self.symbol).grid(row=1, column=1)
        tk.Label(frame, text="Duración").grid(row=1, column=2)
        tk.Entry(frame, textvariable=self.duration, width=5).grid(row=1, column=3)
        ttk.Combobox(frame, textvariable=self.duration_mode, values=["s", "t"], width=5).grid(row=1, column=4)
        tk.Label(frame, text="Stake").grid(row=2, column=0)
        tk.Entry(frame, textvariable=self.stake).grid(row=2, column=1)
        tk.Label(frame, text="Martingala").grid(row=2, column=2)
        tk.Entry(frame, textvariable=self.martingala).grid(row=2, column=3)
        tk.Label(frame, text="Profit Target").grid(row=3, column=0)
        tk.Entry(frame, textvariable=self.profit_target).grid(row=3, column=1)
        tk.Label(frame, text="Stop Loss").grid(row=3, column=2)
        tk.Entry(frame, textvariable=self.stop_loss).grid(row=3, column=3)
        ttk.Combobox(frame, textvariable=self.contract_type, values=["CALL", "PUT", "AMBOS"], width=10).grid(row=4, column=1)

        # Filtros
        tk.Checkbutton(frame, text="RSI", variable=self.rsi_filter).grid(row=5, column=0)
        tk.Checkbutton(frame, text="EMA", variable=self.ema_filter).grid(row=5, column=1)
        tk.Checkbutton(frame, text="CCI", variable=self.cci_filter).grid(row=5, column=2)
        tk.Checkbutton(frame, text="Engulfing", variable=self.engulf_filter).grid(row=5, column=3)
        tk.Checkbutton(frame, text="Todos filtros", variable=self.all_filters).grid(row=5, column=4)

        # Nuevos inputs para configuración de filtros
        tk.Label(frame, text="RSI Min").grid(row=6, column=0)
        tk.Entry(frame, textvariable=self.rsi_min, width=5).grid(row=6, column=1)
        tk.Label(frame, text="RSI Max").grid(row=6, column=2)
        tk.Entry(frame, textvariable=self.rsi_max, width=5).grid(row=6, column=3)

        tk.Label(frame, text="CCI Threshold").grid(row=7, column=0)
        tk.Entry(frame, textvariable=self.cci_threshold, width=5).grid(row=7, column=1)

        tk.Label(frame, text="EMA Rápida").grid(row=7, column=2)
        tk.Entry(frame, textvariable=self.ema_fast, width=5).grid(row=7, column=3)
        tk.Label(frame, text="EMA Lenta").grid(row=7, column=4)
        tk.Entry(frame, textvariable=self.ema_slow, width=5).grid(row=7, column=5)

        tk.Label(frame, text="Modo Engulfing").grid(row=8, column=0)
        ttk.Combobox(frame, textvariable=self.engulf_mode, values=["standard", "strict"], width=10).grid(row=8, column=1)

        # Botones de control
        tk.Button(frame, text="Iniciar", command=self.start).grid(row=9, column=0)
        tk.Button(frame, text="Detener", command=self.stop).grid(row=9, column=1)
        tk.Button(frame, text="Refresh", command=self.refresh).grid(row=9, column=2)
        self.status = tk.Label(frame, text="Ganadas: 0 | Perdidas: 0 | Neto: 0.00")
        self.status.grid(row=9, column=3, columnspan=2)

        self.progress = ttk.Progressbar(self.root, length=500, mode="determinate")
        self.progress.pack()
        self.log = tk.Text(self.root, height=15)
        self.log.pack()

    # Continuará en tercera parte (por longitud)

    def log_message_bloque(self, tipo, resultado, ganancia, stake, saldo, efectividad, filtros):
        hora = datetime.datetime.now().strftime("%H:%M:%S")
        bloque = f"""==========================
[Hora: {hora}] | Señal: {tipo}
Resultado: {resultado}
Filtros: {filtros}
Ganancia: {ganancia:+.2f} | Stake: {stake:.2f}
Saldo: ${saldo:.2f} | Efectividad: {efectividad:.1f}%
==========================\n"""
        self.log.insert(tk.END, bloque)
        self.log.see(tk.END)

    def connect(self):
        self.api = DerivAPI(self.token.get())
        success, msg = self.api.connect()
        if success:
            self.log_message_bloque("Sistema", "Autenticado", 0, 0, self.api.balance, 0, msg)
        else:
            self.log_message_bloque("Sistema", "Error", 0, 0, 0, 0, msg)

    def disconnect(self):
        if self.api:
            self.api.close()
            self.log_message_bloque("Sistema", "Desconectado", 0, 0, self.api.balance, 0, "Conexión cerrada")

    def refresh(self):
        self.log.delete("1.0", tk.END)
        self.ganadas = 0
        self.perdidas = 0
        self.neto = 0.0
        self.update_status()

    def update_status(self):
        self.status.config(text=f"Ganadas: {self.ganadas} | Perdidas: {self.perdidas} | Neto: {self.neto:.2f}")

    def start(self):
        if not self.operating:
            self.operating = True
            threading.Thread(target=self.run).start()

    def stop(self):
        self.operating = False
        self.log_message_bloque("Sistema", "Detenido", 0, 0, self.api.balance, 0, "Bot detenido")

    def calculate_rsi(self, prices, period=14):
        prices = np.array(prices)
        deltas = np.diff(prices)
        seed = deltas[:period]
        up = seed[seed > 0].sum() / period
        down = -seed[seed < 0].sum() / period
        rs = up / down if down != 0 else 0
        rsi = np.zeros_like(prices)
        rsi[:period] = 100. - 100. / (1. + rs)
        for i in range(period, len(prices)):
            delta = deltas[i - 1]
            upval = max(delta, 0)
            downval = -min(delta, 0)
            up = (up * (period - 1) + upval) / period
            down = (down * (period - 1) + downval) / period
            rs = up / down if down != 0 else 0
            rsi[i] = 100. - 100. / (1. + rs)
        return rsi[-1]

    def calculate_ema(self, prices, period=10):
        prices = np.array(prices)
        weights = np.exp(np.linspace(-1., 0., period))
        weights /= weights.sum()
        a = np.convolve(prices, weights, mode='full')[:len(prices)]
        a[:period] = a[period]
        return a[-1]

    def calculate_cci(self, prices, period=14):
        tp = np.array(prices)
        sma = np.mean(tp[-period:])
        mad = np.mean(np.abs(tp[-period:] - sma))
        cci = (tp[-1] - sma) / (0.015 * mad) if mad != 0 else 0
        return cci

    def check_engulfing(self, prices):
        if len(prices) < 4:
            return False
        current_close = prices[-1]
        current_open = prices[-2]
        prev_close = prices[-3]
        prev_open = prices[-4]
        if self.engulf_mode.get() == "standard":
            return current_close > current_open and prev_close < prev_open
        elif self.engulf_mode.get() == "strict":
            body_current = abs(current_close - current_open)
            body_previous = abs(prev_close - prev_open)
            return (current_close > current_open and
                    prev_close < prev_open and
                    body_current > body_previous)
        return False
        if len(prices) < 3:
            return False
        open_list = prices[:-1]
        close_list = prices[1:]
        return close_list[-1] > open_list[-1] and close_list[-2] < open_list[-2]

    def run(self):
        stake_actual = self.stake.get()
        nivel = 0
        esperando_nueva_senal = False
        while self.operating:
            if self.neto >= self.profit_target.get():
                self.log_message_bloque("Sistema", "Stop", 0, stake_actual, self.api.balance + self.neto, 100, "🎯 Profit Target")
                self.stop()
                break
            if self.neto <= self.stop_loss.get():
                self.log_message_bloque("Sistema", "Stop", 0, stake_actual, self.api.balance + self.neto, 0, "🛑 Stop Loss")
                self.stop()
                break

            prices = self.api.get_ticks(self.symbol.get(), 100)
            if not prices:
                self.log_message_bloque("Sistema", "Error", 0, 0, 0, 0, "No hay precios")
                break

            filtros_activos = []
            condiciones = []

            if self.rsi_filter.get():
                if self.rsi_filter.get():
                    pass
                rsi_val = self.calculate_rsi(prices)
                filtros_activos.append("RSI")
                condiciones.append(self.rsi_min.get() < rsi_val < self.rsi_max.get())
            if self.ema_filter.get():
                if self.ema_filter.get():
                    pass
                ema_fast_val = self.calculate_ema(prices, self.ema_fast.get())
                ema_slow_val = self.calculate_ema(prices, self.ema_slow.get())
                filtros_activos.append("EMA")
                condiciones.append(ema_fast_val > ema_slow_val)
            if self.cci_filter.get():
                if self.cci_filter.get():
                    pass
                cci_val = self.calculate_cci(prices)
                filtros_activos.append("CCI")
                condiciones.append(abs(cci_val) > self.cci_threshold.get())
            if self.engulf_filter.get():
                if self.engulf_filter.get():
                    pass
                engulf_val = self.check_engulfing(prices)
                filtros_activos.append("ENG")
                condiciones.append(engulf_val)

            filtros_str = ", ".join(filtros_activos) if filtros_activos else "Sin filtro"
            filtros_cumplidos = all(condiciones) if self.all_filters.get() else any(condiciones)

            if esperando_nueva_senal:
                if not filtros_cumplidos:
                    esperando_nueva_senal = False
                time.sleep(2)
                continue

            if not filtros_cumplidos:
                self.log_message_bloque("Sistema", "Esperando señal", 0, stake_actual, self.api.balance + self.neto, 0, filtros_str)
                time.sleep(2)
                continue

            tipo = self.contract_type.get()
            if tipo == "AMBOS":
                tipo = "CALL" if prices[-1] > prices[-2] else "PUT"

            contract_id, err = self.api.buy_contract(self.symbol.get(), tipo, self.duration.get(), self.duration_mode.get(), stake_actual)
            if err:
                self.log_message_bloque("Sistema", "Error", 0, stake_actual, self.api.balance + self.neto, 0, err)
                break

            self.progress["maximum"] = self.duration.get()
            for i in range(self.duration.get()):
                if not self.operating:
                    break
                self.progress["value"] = i + 1
                self.root.update()
                time.sleep(1)

            profit = self.api.check_result(contract_id)
            resultado = "GANADA" if profit > 0 else "PERDIDA"
            self.neto += profit
            if profit > 0:
                self.ganadas += 1
                esperando_nueva_senal = True
                nivel = 0
                stake_actual = self.stake.get()
            else:
                self.perdidas += 1
                nivel += 1
                if nivel <= 2:
                    stake_actual *= self.martingala.get()
                else:
                    nivel = 0
                    stake_actual = self.stake.get()

            efectividad = (self.ganadas / (self.ganadas + self.perdidas)) * 100 if (self.ganadas + self.perdidas) > 0 else 0
            self.log_message_bloque(tipo, resultado, profit, stake_actual, self.api.balance + self.neto, efectividad, filtros_str)
            self.update_status()

if __name__ == "__main__":
    root = tk.Tk()
    root.title("BOT_TRADING_FINAL_V8")
    app = TradingBot(root)
    root.mainloop()