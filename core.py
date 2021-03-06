# -*- coding: utf-8 -*-
"""
Created on Sun Mar  8 23:30:40 2020
@author: L
"""

import os
import binance_credentials as creds
import kline_data_mapper as kdm
from binance.client import Client
from binance.websockets import BinanceSocketManager
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import winsound
import matplotlib.pyplot as plt
import seaborn as sns
rc = {'font.family':'cambria', 'font.size':24}
sns.set(context='poster', style='darkgrid', rc=rc)


class TradingRobot:
    
    def __init__(self, client, symbol='BTCUSDT', interval='1m', output_dir=None, active=False, history_start=None):
        
        self.client = client
        self.symbol = symbol
        self.symbol_info = self.client.get_symbol_info(self.symbol)
        self.base = self.symbol_info['baseAsset']
        self.quote = self.symbol_info['quoteAsset']
        self.current_asset = self.get_current_asset()
        self.interval = interval
        self.output_dir = output_dir
        self.active = active
        self.trade_prec = self.symbol_info['filters'][2]['stepSize'].find('1') - 1
        self.history_start = history_start
        self.start_time = datetime.now()
        self.isotimestamp = self.start_time.replace(microsecond=0).isoformat().replace(':', '')
        self.output_fname = f'{self.symbol}_trade_data_{self.isotimestamp}'
        self.output_historical_fname = f'{self.symbol}_historical_trade_data_{self.isotimestamp}'
        self.iterations = 0
        self.data = {}
        self.df = pd.DataFrame()
        
        # outputting
        if self.output_dir == None: self.output_dir = 'output_data'
        
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        self.output_file = f'{self.output_dir}/{self.output_fname}.csv'
        
        
        if self.history_start is not None:
            print("Getting historical data...")
            self.hdf = self._get_historical_data()
            self.hdf.to_csv(f'{self.output_dir}/{self.output_historical_fname}.csv', index=False)
            print("Done.")
        else:
            
            self.hdf = None
        
        return
    
    # Not sure if these are necessary.
    # def set_active(self):
    #     self.active = True
    
    # def set_inactive(self):
    #     self.active = False
    
    def _reorder_keys(self):
        # Run this before converting to output df
        new_key_order = ['timestamp','symbol','event_type',
                         'interval','kline_time','kline_open_time',
                         'kline_close_time',  'event_servertime','time_uncertainty',
                         'first_trade_id','last_trade_id', 'open',
                         'high','low','close',
                         'base_volume','quote_volume','number_of_trades',
                         'EMA_10','EMA_100','closed',
                         'taker_buy_base_volume','taker_buy_quote_volume','source',
                         'trade_action','price_at_trade','fill_quantity',
                         'fill_commission','fill_commission_asset']
        self.data = {k: self.data[k] for k in new_key_order}
    
    def _get_historical_data(self):
        
        # Create timedelta to get exact minute for end of historical data
        history_end = str(self.start_time.replace(second=0, microsecond=0) - timedelta(seconds=1))
        # Get historical klines up until current minute, truncating
        now = datetime.now()
        klines = self.client.get_historical_klines(symbol=self.symbol,interval=self.interval,
                                                   start_str=self.history_start,end_str=history_end)
        print(f"Time taken to retrieve historical data:\n\t{datetime.now() - now}")
        hdf = pd.DataFrame(klines)
        hdf = hdf.iloc[:, :6]
        hdf[0] = pd.to_numeric(hdf[0], downcast='integer')
        hdf.iloc[:, 1:] = hdf.iloc[:, 1:].astype(float)
        hdf.columns = ['servertime', 'open', 'high', 'low', 'close', 'volume']
        # Compute timestamp
        hdf['kline_time'] = pd.to_datetime(hdf['servertime'], unit='ms')
        hdf['source'] = 'historical'
        
        return hdf[['servertime', 'kline_time', 'open', 'high', 'low', 'close', 'volume', 'source']]
    
    def _play_sound(self, freq):
        winsound.Beep(frequency=int(freq), duration=10)
    
    def _stream(self):
        # Initialise the kline socket manager object from Binance
        bsm = BinanceSocketManager(client=self.client)
        conn_key = bsm.start_kline_socket(self.symbol, self._process_output, interval=self.interval)
        
        return bsm, conn_key
    
    def _add_data(self, d):
        # Data must be of type dict
        for k, v in d.items():
            
            self.data.setdefault(k, []).append(v)
            
        return
    
    
    def _write_data(self):
        
        with open(self.output_file, 'a', encoding='utf-8', newline='\n') as f:
            pd.DataFrame(self.df.iloc[-1, :]).T.to_csv(f, header=f.tell() == 0, index=False)
        return
    
    def _process_output(self, output):
        # Callback function to bsm.start_kline_socket()
        acq_time = datetime.now() # data acquisition time
        # Use kdm.mapper dict to rename output keys
        processed_output = {}
        
        for key, val in output.items():
            
            if type(val)==dict:
                
                for kkey, vval in val.items():
                    
                    keyname = kdm.mapper[key][kkey]
                    processed_output[keyname] = output[key][kkey]
                    
            else:
                keyname = kdm.mapper[key]
                processed_output[keyname] = val
                
        del processed_output['ignore']
        
        # Wait until the minute to get the kline data
        c1 = processed_output['event_servertime'] >= processed_output['kline_close_time']
        c2 = processed_output['closed'] == True
        
        if c1 and c2:
            
            # Convert elements to floats
            to_float = ['open', 'high', 'low', 'close', 'base_volume', 'quote_volume', 'taker_buy_base_volume', 'taker_buy_quote_volume']
            processed_output = {k:float(v) if k in to_float else v for (k,v) in processed_output.items()}
            
            # Specify time of acquisition and kline open time, along with time uncertainty between the two
            processed_output['timestamp'] = acq_time
            processed_output['kline_time'] = datetime.fromtimestamp(processed_output['kline_open_time']/1000)
            processed_output['time_uncertainty'] = processed_output['timestamp'] - processed_output['kline_time']
            processed_output['source'] = 'acquired'
            
            # Add this data to the data object
            self._add_data(d=processed_output)
            
            # Define what to put into the model
            model_input = self._specify_model_input()
            
            # Create the model
            # SMA = SimpleMovingAverage(y='close', data=model_input)
            model = ExponentialMovingAverage(y='close', data=model_input, window=(10, 100))
            
            # Fit the model
            self.model_output = model.fit()
            
            # Evaluate the model output and buy/hold/sell accordingly
            self.get_current_asset() # update the current asset
            
            if self.active == True:
                
                print("\t\tState: Active")
                # Make trades here
                self.make_trade()
                
            else:
                
                print("\t\tState: Inactive")
                self.make_trade()
            
            
            # Specify the last row i.e. current iteration
            to_add = self.model_output.iloc[-1, 3:].to_dict()
            
            # Add to the dataset
            self._add_data(d=to_add)
            
            # add the trade output to the dataset
            self._add_data(d=self.last_order)
            
            # Reorder the data
            self._reorder_keys()
            
            self.df = pd.DataFrame(self.data)
            
            self.iterations += 1
            
            self._write_data()
            
            print(pd.Series(self.df.iloc[-1, :].to_dict()))
            print("Iteration number: ", self.iterations)
            
            self._play_sound(1500)
    
    
    def _specify_model_input(self):
        
        cols = ['kline_time', 'close', 'source']
        current_df = pd.DataFrame(
            {'kline_time':self.data['kline_time'],
             'close':self.data['close'], 'source':self.data['source']})
        
        return pd.concat([self.hdf[cols], current_df]).reset_index(drop=True)
    
    def get_balance(self, asset):
        return float(self.client.get_asset_balance(asset)['free'])
    
    def get_base_as_quote(self):
        return self.get_symbol_price() * self.get_balance(self.base)
    
    def get_current_asset(self):
        
        if self.get_base_as_quote() > self.get_balance(self.quote):
            
            self.current_asset = self.base
            print(f"\tCurrent asset: {self.base}")
            
        else:
            
            self.current_asset = self.quote
            print(f"\tCurrent asset: {self.quote}")
        
        return self.current_asset
    
    def get_symbol_price(self):
        return float(self.client.get_symbol_ticker(symbol=self.symbol)['price'])
    
    def buy(self, scale=1):
        
        if self.active:
            
            if self.get_current_asset() == self.base:
                
                print(f"\tHolding {self.base}, can't buy...")
                
                return {} # empty order
            
            print(f"\tHolding {self.quote}...")
            
            quote_balance = self.get_balance(asset=self.quote)
            base_value = self.get_symbol_price()
            quantity = scale * np.floor(quote_balance / base_value * 10 ** self.trade_prec) / 10 ** self.trade_prec           
            place_order = self.client.create_order
            
        else:
            
            quantity = 0.002
            place_order = self.client.create_test_order
    
        while True:
            
            try:
                
                order = place_order(symbol=self.symbol, side='BUY', type='MARKET', quantity=quantity)
                self.get_current_asset()
                
                break
            
            except:
                
                quantity -= 1*10**-self.trade_prec
                print(f"reducing trade quantity to {quantity}")
                
                pass
        return order
    
    def sell(self, scale=1):
        if self.active:
            
            if self.get_current_asset() == self.quote:
                
                print(f"\tHolding {self.quote}, can't sell...")
                
                return {} # empty order, no trade made
            
            print(f"\tHolding {self.base}")
            
            base_balance = self.get_balance(self.base)
            quantity = np.floor(base_balance * scale * 10 ** self.trade_prec) / 10 ** self.trade_prec  # Round down to nearest prec-digit float.
            place_order = self.client.create_order
            
        else:
            
            place_order = self.client.create_test_order
            quantity = 0.002
        
        while True:
            
            try:
                
                order = place_order(symbol=self.symbol, side='SELL', type='MARKET', quantity=quantity)
                self.get_current_asset()
                
                break
            
            except:
                
                quantity -= 1*10**-self.trade_prec
                print(f"reducing trade quantity to {quantity}")
                
                pass
        
        return order
    
    def make_trade(self):
        
        # Check for crossover
        if self.model_output.iloc[-1, -2] > self.model_output.iloc[-1, -1]:
            
            trade_output = self.buy()
            
        else:
            
            trade_output = self.sell()
        
        self.last_order = {}
        # Data logging
        if trade_output == {}:
            # Nothing happened
            self.last_order['trade_action'] = 'HOLD'
            self.last_order['price_at_trade'] = None
            self.last_order['fill_quantity'] = None
            self.last_order['fill_commission'] = None
            self.last_order['fill_commission_asset'] = None
            
        else:
            # Either bought or sold
            self.last_order['trade_action'] = trade_output['side']
            self.last_order['price_at_trade'] = float(trade_output['fills'][0]['price'])
            self.last_order['fill_quantity'] = float(trade_output['fills'][0]['qty'])
            self.last_order['fill_commission'] = float(trade_output['fills'][0]['commission'])
            self.last_order['fill_commission_asset'] = trade_output['fills'][0]['commissionAsset']
    
        return
    
    def start(self):
        
        #print(f"Run start: {self.start_time}")
        self.bsm, self.conn_key = self._stream()
        self.bsm.start()
        
        return self.bsm, self.conn_key
    
    def stop(self):
        
        stop_time = datetime.now()
        
        print(f"Started: {str(self.start_time)}")
        print(f"Stopped: {str(stop_time)}")
        print(f"Duration: {str(stop_time - self.start_time)}")
        
        self.bsm.close()
    
    def plot(self, all_data=True):
        
        fig, ax = plt.subplots()
        
        if all_data == True:
            
            to_plot = self.model_output.set_index('kline_time')
            
        else:
            
            to_plot = self.model_output.loc[self.model_output['source']=='acquired'].set_index('kline_time')
        
        to_plot.plot(ax=ax)
        
        plt.show()
        
        

# Later create entire module of models
class SimpleMovingAverage:
    
    def __init__(self, y, data, window=[10, 100]):
        
        self.y = y # Ensure that y is a pandas dataframe
        self.data = data.copy()
        self.window = window
        
        return
    
    def fit(self):
        
        fast = self.data[self.y].rolling(window=self.window[0]).mean()
        slow = self.data[self.y].rolling(window=self.window[1]).mean()
        
        self.data[f'SMA_{self.window[0]}'] = fast
        self.data[f'SMA_{self.window[1]}'] = slow

        return self.data

class ExponentialMovingAverage:
    
    def __init__(self, y, data, window=(10,100)):
        
        self.y = y
        self.data = data.copy()
        self.window = window
        
        return
    
    def fit(self):
        
        fast = self.data[self.y].ewm(span=self.window[0], min_periods=self.window[0]).mean()
        slow = self.data[self.y].ewm(span=self.window[1], min_periods=self.window[1]).mean()
        self.data[f'EMA_{self.window[0]}'] = fast
        self.data[f'EMA_{self.window[1]}'] = slow
        
        return self.data
        
    
    
if __name__ == '__main__':
    
    client = Client(api_key=creds.api_key, api_secret=creds.api_secret)
    
    BTC_listing_origin = '1 day ago UTC' #'17 Aug, 2017'
    
    bot = TradingRobot(client=client,
                       symbol='BTCUSDT',
                       interval='1m',
                       active=False,
                       history_start=BTC_listing_origin)
    bot.start()
