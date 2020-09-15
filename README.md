# SDN Traceroute
Ryu Controller Application with binary search traceroute functionality in Software-Defined Networking (SDN) with OpenFlow 1.3, implemented using Python, RYU SDN Framework, Dragon Knight, Mininet.

# Usage
1. Install [RYU SDN Framework](https://github.com/faucetsdn/ryu), [Dragon Knight](https://github.com/Ryu-Dragon-Knight/Dragon-Knight), [Mininet](https://github.com/mininet/mininet)(for testing).
2. Copy simple_switch_13_5.py to /usr/lib/python3/dist-packages/ryu/app/.


3. Run dragon-knight daemon.
4. Run dragon-knight.
5. Type the following in dragon-knight command line.
```
install ryu.app.simple_switch_13_5
```
  Now, the controller will run in the dragon-knight daemon.
  
6. Run mininet, Using mininet to test the topology. (the third CMD)
# Why dragon-knight
We need to commuicate with controller via command line. We try to create a thread to implement this function, but it seems doesn't work in Python. However, dragon-knight provide a UI to solve this problem.

# Demo example
By simple, we can test linear topology in mininet.
```
sudo mn --topo linear,5 --mac --switch ovsk,protocols=OpenFlow13 --controller remote
```
Now, linear topology is build. Then type the following in dragon-knight command line.
```
tr h3 h5
```
It will show the result in dragon-knight daemon.
