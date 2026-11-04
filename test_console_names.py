import socket,unittest
from unittest.mock import patch
from console_names import STRIPS,name_query,parse_name,osc_string,fetch_names

class NamesTests(unittest.TestCase):
    def test_all_outgoing_messages_are_argument_free_name_reads(self):
        for strip in STRIPS:
            for effective in (True,False):
                packet=name_query(strip,effective)
                self.assertTrue(packet.endswith(b',\0\0\0'))
                self.assertEqual(len(packet)%4,0)
                address='/'+strip+('/$name' if effective else '/name')
                self.assertEqual(packet,osc_string(address)+osc_string(','))
        for bad in ('ch/0','ch/41','ch/1/mute','ch/1/name,','aux/9','/ch/1'):
            with self.assertRaises(ValueError):name_query(bad)
    def test_parser_rejects_nonname_and_invalid_messages(self):
        self.assertEqual(parse_name(osc_string('/ch/1/$name')+osc_string(',s')+osc_string('Lead Vox')),('ch/1','Lead Vox'))
        for packet in (b'garbage',osc_string('/ch/1/mute')+osc_string(',i')+b'\0'*4,osc_string('/ch/41/name')+osc_string(',s')+osc_string('Bad')):
            self.assertIsNone(parse_name(packet))
    def test_fetch_only_sends_names_and_accepts_matching_replies(self):
        sent=[];replies=[]
        class Socket:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def settimeout(self,value):pass
            def sendto(self,packet,peer):
                sent.append((packet,peer));address=packet.split(b'\0',1)[0].decode()
                replies.append((osc_string(address)+osc_string(',s')+osc_string('Console Name'),peer))
            def recvfrom(self,size):
                if replies:return replies.pop(0)
                raise socket.timeout()
        with patch('console_names.socket.socket',return_value=Socket()):result=fetch_names('10.1.10.20')
        self.assertEqual(set(result),set(STRIPS));self.assertEqual(len(sent),48)
        self.assertTrue(all(packet.endswith(b',\0\0\0') and peer==('10.1.10.20',2223) for packet,peer in sent))
    def test_unicast_validation(self):
        for ip in ('not-an-ip','255.255.255.255','0.0.0.0','224.0.0.1'):
            with self.assertRaises(ValueError):fetch_names(ip)

if __name__=='__main__':unittest.main()
