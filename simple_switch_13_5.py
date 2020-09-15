# Copyright (C) 2011 Nippon Telegraph and Telephone Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.lib.packet import *

from ryu.topology import event, switches
from ryu.topology.api import get_switch, get_link, get_all_switch
from ryu.lib import hub
import time
import signal
import copy
class SimpleSwitch13_5(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    

    def __init__(self, *args, **kwargs):
        super(SimpleSwitch13_5, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.dp = {}
        self.fe = {}
        self.S = []
        self.L = []
        self.tr_start_time=0
        self.tr_send_time=float('inf')

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):   
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # install table-miss flow entry
        #
        # We specify NO BUFFER to max_len of the output action due to
        # OVS bug. At this moment, if we specify a lesser number, e.g.,
        # 128, OVS will send Packet-In with invalid buffer_id and
        # truncated packet data. In that case, we cannot output packets
        # correctly.  The bug has been fixed in OVS v2.1.0.
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

        self.dp[datapath.id] = datapath

    def add_flow(self, datapath, priority, match, actions, buffer_id=None):
        dpid = datapath.id
        self.fe.setdefault(dpid, [])
        t = (match['in_port'] if 'in_port' in match else None, match['eth_dst'] if 'eth_dst' in match else None, actions[0].port if len(actions) > 0 and hasattr(actions[0], 'port') else None)
        if t not in self.fe[dpid]:
            self.fe[dpid].append(t)

        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, instructions=inst)
        datapath.send_msg(mod)
        time.sleep(0.01)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        # If you hit this you might want to increase
        # the "miss_send_length" of your switch

        msg = ev.msg
        datapath = msg.datapath

        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        src = eth.src
        dst = eth.dst

        dpid = datapath.id


        self.S = list(set(self.S + [s.dp.id for s in get_switch(self, None)]))
        self.L = list(set(self.L + [(l.src.dpid, l.dst.dpid, l.src.port_no) for l in get_link(self, None)]))

        if self.tr_send_time<time.time():
            self.trac_send()

        if self.tr_start_time>0 and time.time()-self.tr_start_time>1:
            self.tr_result=False
            self.trac()

        if dpid in self.fe and len([0 for a in self.fe[dpid] if a[0]==in_port and a[1]==dst])>0:
            pkt_ipv4=pkt.get_protocol(ipv4.ipv4)
            if pkt_ipv4 and pkt_ipv4.src=='10.7.10.7':
                self.tr_result=True
                self.trac()
            return


        if ev.msg.msg_len < ev.msg.total_len:
            self.logger.debug("packet truncated: only %s of %s bytes",
                              ev.msg.msg_len, ev.msg.total_len)

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        if src[:2] != '00' and dst[:2] != '00':
            return

        
        self.mac_to_port.setdefault(dpid, {})

        # learn a mac address to avoid FLOOD next time.
        self.mac_to_port[dpid][src] = in_port

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # install a flow to avoid packet_in next time
        if out_port != ofproto.OFPP_FLOOD:

            self.add_flow_path(dpid, src, dst)

            match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
            # verify if we have a valid buffer_id, if yes avoid to send both
            # flow_mod & packet_out
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(datapath, 1, match, actions, msg.buffer_id)
                return
            else:
                self.add_flow(datapath, 1, match, actions)
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)

    @set_ev_cls(event.EventSwitchEnter)
    def event_switch_enter_handler(self, ev):
        self.switch = [s.dp.id for s in get_switch(self, None)]
        self.link = [(l.src.dpid, l.dst.dpid, {'port': l.src.port_no}) for l in get_link(self, None)]

    def set_tr_end(self, dpid, in_port, dst, out_port):
        datapath=self.dp[dpid]
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        actions.append(parser.OFPActionOutput(out_port))
        self.add_flow(datapath, 2, match, actions)

    def clear_tr_end(self, dpid, in_port, dst):
        datapath=self.dp[dpid]
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
        mod=parser.OFPFlowMod(datapath=datapath, command=ofproto.OFPFC_DELETE_STRICT
            , out_port=ofproto.OFPP_ANY, out_group=ofproto.OFPG_ANY
            , match=match, priority=2)
        datapath.send_msg(mod)
        time.sleep(0.01)

    def send_flow_mod(self, datapath,in_port,eth_dst):
        ofproto = datapath.ofproto
        ofp_parser = datapath.ofproto_parser
        
        match = ofp_parser.OFPMatch(in_port=in_port, eth_dst=eth_dst)
        actions = [ofp_parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 2, match, actions)

    def send_packet_out(self, dpid, src, dst, out_port):
        datapath=self.dp[dpid]
        ofproto=datapath.ofproto
        parser=datapath.ofproto_parser
        pkt=packet.Packet()
        pkt.add_protocol(ethernet.ethernet(
            ethertype=ether_types.ETH_TYPE_IP, src=src, dst=dst))
        pkt.add_protocol(ipv4.ipv4(src='10.7.10.7'))
        pkt.serialize()
        data=pkt.data
        actions=[parser.OFPActionOutput(port=out_port)]
        req=parser.OFPPacketOut(datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=ofproto.OFPP_CONTROLLER, actions=actions, data=data)
        datapath.send_msg(req)

    def add_flow_c(self, dpid, in_port, eth_dst, out_port):
        datapath = self.dp[dpid]
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        actions = [parser.OFPActionOutput(out_port)]
        match = parser.OFPMatch(in_port=in_port, eth_dst=eth_dst)
        self.add_flow(datapath, 1, match, actions)

    def add_flow_path(self, dpid, src, dst):
        self.l = [(l.src.dpid, l.dst.dpid, {'port': l.src.port_no}) for l in get_link(self, None)]
        self.add_flow_c(dpid, self.mac_to_port[dpid][dst], src, self.mac_to_port[dpid][src])
        while dst in self.mac_to_port[dpid].keys() and len([0 for a in self.l if a[0] == dpid and a[2]['port'] == self.mac_to_port[dpid][dst]]) > 0:
            pre = dpid
            dpid = [a[1] for a in self.l if a[0] == dpid and a[2]['port'] == self.mac_to_port[dpid][dst]][0]
            in_port = self.mac_to_port[dpid][dst]
            out_port = [a[2]['port'] for a in self.l if a[0] == dpid and a[1] == pre][0]

            self.add_flow_c(dpid, in_port, src, out_port)
            self.add_flow_c(dpid, out_port, dst, in_port)


    def addr_to_name(self, s):
        return 'h'+str(int(''.join(s.split(':')), 16))

    def name_to_addr(self, s):
        t = hex(int(s[1:]))[2:]
        t = '0'*(12-len(t))+t
        t = ''.join([t[i:i+2]+(':' if i<10 else '') for i in range(0, 12, 2)])
        return t

    def find_access_switch(self, addr, L):
        for s, m in self.mac_to_port.items():
            for dst, outp in m.items():
                if dst==addr and len([0 for l in L if l[0]==s and l[2]==outp])==0:
                    return (s, outp)
        return (None, None)

    def tr(self, src_name, dst_name):

        self.E = copy.deepcopy(self.fe)

        for s, v in self.E.items():
            for i in range(len(v)):
                t = [l[1] for l in self.L if l[0]==s and l[2]==v[i][2]]
                if len(t)>0:
                    t = [(l[0], l[2]) for l in self.L if l[0]==t[0] and l[1]==s][0]
                else:
                    t = (None, None)
                v[i] += t
        self.src = self.name_to_addr(src_name)
        self.dst = self.name_to_addr(dst_name)
        self.u, self.inp = self.find_access_switch(self.src, self.L)
        self.v, self.outp = self.find_access_switch(self.dst, self.L)

        if self.u is None or self.v is None:
            print("\033[92m\n\nFail\n\033[0m")
            if self.u is None:
                self.logger.info("\033[92m   unknown host : %s(%s)\n\033[0m", src_name, self.src)
            if self.v is None:
                self.logger.info("\033[92m   unknown host : %s(%s)\n\033[0m", dst_name, self.dst)
            return

        self.rt = [self.u]
        self.rtp = [self.inp]

        while self.u in self.E and len([0 for a in self.E[self.u] if a[0]==self.inp and a[1]==self.dst and a[3] is not None])>0:
            self.u, self.inp=[(a[3], a[4]) for a in self.E[self.u] if a[0]==self.inp and a[1]==self.dst][0]
            self.rt.append(self.u)
            self.rtp.append(self.inp)

        if self.rt[-1]!=self.v or self.v not in self.E or len([0 for a in self.E[self.v] if a[0]==self.inp and a[1]==self.dst])==0:
            print("\033[92m\n\nFail\n\033[0m")
            self.logger.info("\033[92m   %s(%s) cannot reach %s(%s)\n\033[0m", src_name, self.src, dst_name, self.dst)
            return

        self.tr_state=0
        self.trac()
        
    def trac(self):

        if self.tr_state==0:
            self.logger.info("\033[92m\n\n======   starting traceroute ======\n\033[0m")
            self.tr_state=1

        if self.tr_state==1:
            self.logger.info("\033[92m\ntraditional traceroute\n\033[0m")
            self.l, self.r=0, 1
            self.tr_state=2

        if self.tr_state==2:
            if self.tr_start_time>0:
                self.tr_start_time=0
                self.clear_tr_end(self.v, self.inpv, self.dst)
                self.logger.info("\033[92m   tr : %s \033[0m", self.rt[:self.r+1])
                self.logger.info("\033[92m      result: "+("" if self.tr_result else "not ")+"ok\n\033[0m")
                self.r+=1
            if self.r < len(self.rt):
                self.u, self.inpu=self.rt[0], self.rtp[0]
                self.outpu=[a[2] for a in self.E[self.u] if a[0]==self.inpu and a[1]==self.dst][0]
                self.v, self.inpv=self.rt[self.r], self.rtp[self.r]
                self.outpv=[a[2] for a in self.E[self.v] if a[0]==self.inpv and a[1]==self.dst][0]
                self.set_tr_end(self.v, self.inpv, self.dst, self.outpv)
                self.tr_send_time=time.time()+1
            else:
                self.tr_state=3

        if self.tr_state==3:
            self.logger.info("\033[92m\nchecking for any failed link(binary search)\n\033[0m")
            self.lend, self.rend=0, len(self.rt)-1
            self.l, self.r=self.lend, self.rend
            self.fl=[]
            self.tr_state=4

        if self.tr_state==4:
            if self.tr_start_time>0:
                self.tr_start_time=0
                self.clear_tr_end(self.v, self.inpv, self.dst)
                self.logger.info("\033[92m   testing route: %s\033[0m", self.rt[self.l:self.m+1])
                if self.tr_result:
                    self.logger.info("\033[92m      result: ok\n\033[0m")
                    self.l=self.m
                else:
                    self.logger.info("\033[92m      result: not ok\n\033[0m")
                    self.r=self.m-1
                if self.l>=self.r:
                    if self.r<self.rend:
                        self.fl.append((self.rt[self.r], self.rt[self.r+1]))
                    self.lend=self.r+1
                    self.l, self.r=self.lend, self.rend
            if self.l<self.r:
                self.m=(self.l+self.r+1)//2
                self.u, self.inpu=self.rt[self.l], self.rtp[self.l]
                self.outpu=[a[2] for a in self.E[self.u] if a[0]==self.inpu and a[1]==self.dst][0]
                self.v, self.inpv=self.rt[self.m], self.rtp[self.m]
                self.outpv=[a[2] for a in self.E[self.v] if a[0]==self.inpv and a[1]==self.dst][0]
                self.set_tr_end(self.v, self.inpv, self.dst, self.outpv)
                self.tr_send_time=time.time()+1
            else:
                if len(self.fl)==0:
                    self.logger.info("\033[92mno failed link\033[0m")
                else:
                    self.logger.info("\033[92mfailed link:\033[0m")
                    for u, v in self.fl:
                        self.logger.info("\033[92ms%s -> s%s\033[0m", u, v)
                self.tr_state=5

        if self.tr_state==5:
            self.logger.info("\033[92m\n\n======   traceroute done ======\n\n\033[0m")
            self.tr_state=6

    def trac_send(self):
        self.tr_send_time=float('inf')
        self.send_packet_out(self.u, self.src, self.dst, self.outpu)
        self.tr_start_time=time.time()
