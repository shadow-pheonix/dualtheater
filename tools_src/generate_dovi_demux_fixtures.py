"""Generate tiny original Matroska demux fixtures. NAL picture bytes are placeholders, not decode samples."""
from pathlib import Path
r=Path(__file__).resolve().parent.parent
fixtures=r/'android/app/src/test/resources/dovi'
def vint(n):
 for width in range(1,9):
  if n < (1<<(7*width))-1:return ((1<<(7*width))|n).to_bytes(width,'big')
 raise ValueError('length too large')
def element(key,data):return key.to_bytes((key.bit_length()+7)//8,'big')+vint(len(data))+data
def integer(key,n):return element(key,n.to_bytes(max(1,(n.bit_length()+7)//8),'big'))
def main():
 ebml=element(0x1A45DFA3,integer(0x4286,1)+integer(0x42F7,1)+element(0x4282,b'matroska')+integer(0x4287,4)+integer(0x4285,2))
 # Legal empty hvcC array set: enough to test container wiring, not decoding.
 hvcc=bytes([1,1,0,0,0,0,0,0,0,0,0,0,153,0xf0,0,0xfc,0xfd,0xfa,0xfa,0,0,3,0])
 video=element(0xE0,integer(0xB0,16)+integer(0xBA,16))
 mapping=element(0x41E4,integer(0x41E7,0x64766343)+element(0x41ED,bytes([1,0,14,55,16])))
 track=element(0xAE,integer(0xD7,1)+integer(0x73C5,1)+integer(0x83,1)+element(0x86,b'V_MPEGH/ISO/HEVC')+element(0x63A2,hvcc)+video+mapping)
 info=element(0x1549A966,integer(0x2AD7B1,1_000_000))
 for kind in ('p7-mel','p7-fel'):
  nalus=[bytes([0x26,1,4,5,6]),(fixtures/(kind+'.bin')).read_bytes(),bytes([0x7e,1,9,8,7])]
  sample=b''.join(len(nal).to_bytes(4,'big')+nal for nal in nalus)
  cluster=element(0x1F43B675,integer(0xE7,0)+element(0xA3,bytes([0x81,0,0,0x80])+sample))
  (fixtures/(kind+'.mkv')).write_bytes(ebml+element(0x18538067,info+element(0x1654AE6B,track)+cluster))
if __name__=='__main__':main()
